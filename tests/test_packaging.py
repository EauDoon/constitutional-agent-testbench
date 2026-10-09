"""Guard the installed command surface against un-shipped entry points."""

import ast
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class ConsoleScriptTests(unittest.TestCase):
    def setUp(self):
        self.distribution = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
        self.shipped = {path.name for path in PACKAGE_ROOT.iterdir()
                        if (path / "__init__.py").is_file()}

    def test_every_entry_point_targets_a_shipped_package(self):
        scripts = self.distribution["project"]["scripts"]
        self.assertTrue(scripts)
        for name, target in sorted(scripts.items()):
            module, _, attribute = target.partition(":")
            with self.subTest(script=name):
                self.assertTrue(attribute)
                self.assertIn(module.split(".", 1)[0], self.shipped)
                entry = getattr(__import__(module, fromlist=["__name__"]), attribute)
                self.assertTrue(callable(entry))

    def test_package_data_and_typed_marker_are_declared(self):
        package_data = self.distribution["tool"]["setuptools"]["package-data"]
        self.assertIn("py.typed", package_data["constitutional_agent_testbench"])
        self.assertTrue((PACKAGE_ROOT / "constitutional_agent_testbench" / "py.typed").is_file())


class LicenseMetadataTests(unittest.TestCase):
    """The declared license must match the shipped LICENSE text."""

    def setUp(self):
        self.project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]

    def test_declared_license_is_apache(self):
        self.assertEqual(self.project["license"], "Apache-2.0")
        self.assertFalse(
            [item for item in self.project.get("classifiers", []) if item.startswith("License ::")],
            "PEP 639 forbids a License classifier beside a license expression",
        )

    def test_license_file_is_the_apache_text(self):
        # Line 1 of the Apache text is indented, so strip before comparing.
        text = (ROOT / "LICENSE").read_text("utf-8").lstrip()
        self.assertTrue(text.startswith("Apache License"))

    def test_license_files_ship_license_and_notice(self):
        declared = self.project["license-files"]
        for name in ("LICENSE", "NOTICE"):
            with self.subTest(file=name):
                self.assertIn(name, declared)
                self.assertTrue((ROOT / name).is_file())

    def test_manifest_includes_notice(self):
        lines = (ROOT / "MANIFEST.in").read_text("utf-8").splitlines()
        self.assertIn("include NOTICE", lines)

    def test_readme_states_the_current_license(self):
        readme = (ROOT / "README.md").read_text("utf-8")
        self.assertIn("Apache License 2.0", readme)
        self.assertNotIn("Released under the MIT License", readme)


def _repository_packages_imported_by_tests() -> set[str]:
    """Top-level names the tests import that resolve to a package at the root."""

    found: set[str] = set()
    for path in sorted((ROOT / "tests").glob("*.py")):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".", 1)[0]
                if (ROOT / top / "__init__.py").is_file():
                    found.add(top)
    return found


class SourceDistributionTests(unittest.TestCase):
    """Tests ship in the sdist, so everything they import must ship too."""

    def test_sdist_ships_every_repository_package_the_tests_import(self):
        packages = _repository_packages_imported_by_tests()
        self.assertIn("evals", packages)
        manifest = (ROOT / "MANIFEST.in").read_text("utf-8").splitlines()
        for package in sorted(packages):
            with self.subTest(package=package):
                covering = [
                    line.split()[2:]
                    for line in manifest
                    if line.split()[:2] == ["recursive-include", package]
                ]
                self.assertTrue(
                    any("*.py" in patterns for patterns in covering),
                    f"MANIFEST.in must ship {package}/ Python files for the sdist tests",
                )


class AdopterScriptTests(unittest.TestCase):
    def test_adopter_checks_survive_python_optimize(self):
        # `python -O` strips assert statements, so the adopter oracle must
        # fail through explicit raises to keep "passed=true" meaningful.
        script = ROOT / "scripts" / "verify_installed_workflow.py"
        tree = ast.parse(script.read_text("utf-8"), filename=str(script))
        bare = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        self.assertEqual(bare, [])


class ProjectMetadataTests(unittest.TestCase):
    def setUp(self):
        self.project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]

    def test_project_urls_are_declared(self):
        urls = self.project["urls"]
        for name in ("Source", "Changelog", "Issues"):
            with self.subTest(url=name):
                self.assertTrue(urls[name].startswith("https://github.com/EauDoon/"))

    def test_typed_classifier_matches_the_shipped_marker(self):
        self.assertIn("Typing :: Typed", self.project["classifiers"])

    @unittest.skipUnless(CI_WORKFLOW.is_file(), "repository-only check; the sdist has no .github/")
    def test_python_classifiers_match_the_ci_matrix(self):
        match = re.search(r'^\s*python:\s*\[([^\]]*)\]', CI_WORKFLOW.read_text("utf-8"), re.MULTILINE)
        self.assertIsNotNone(match)
        tested = {item.strip().strip('"\'') for item in match.group(1).split(",")}
        prefix = "Programming Language :: Python :: 3."
        declared = {
            item.removeprefix("Programming Language :: Python :: ")
            for item in self.project["classifiers"]
            if item.startswith(prefix)
        }
        self.assertEqual(declared, tested)


@unittest.skipUnless(CI_WORKFLOW.is_file(), "repository-only check; the sdist has no .github/")
class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.workflow = CI_WORKFLOW.read_text("utf-8")

    def test_main_runs_are_never_cancelled(self):
        settings = re.findall(r"^\s*cancel-in-progress:\s*(.+)$", self.workflow, re.MULTILINE)
        self.assertEqual(settings, ["${{ github.event_name == 'pull_request' }}"])

    def test_lint_job_uses_the_documented_ruff_pin(self):
        pins = set(re.findall(r"ruff==[0-9.]+", self.workflow))
        self.assertEqual(len(pins), 1)
        self.assertIn(pins.pop(), (ROOT / "CONTRIBUTING.md").read_text("utf-8"))
        self.assertIn("python -m ruff check --no-cache .", self.workflow)

    def test_coverage_floor_is_enforced_with_the_documented_pin(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["tool"]["coverage"]
        self.assertTrue(config["run"]["branch"])
        self.assertEqual(config["run"]["source_pkgs"], ["constitutional_agent_testbench"])
        self.assertGreaterEqual(config["report"]["fail_under"], 95)
        pins = set(re.findall(r"coverage==[0-9.]+", self.workflow))
        self.assertEqual(len(pins), 1)
        self.assertIn(pins.pop(), (ROOT / "CONTRIBUTING.md").read_text("utf-8"))
        self.assertIn("python -m coverage report", self.workflow)

    def test_dependabot_tracks_pinned_actions(self):
        config = (ROOT / ".github" / "dependabot.yml").read_text("utf-8")
        self.assertIn("package-ecosystem: github-actions", config)
        self.assertRegex(config, r"default-days:\s*14")


if __name__ == "__main__":
    unittest.main()
