"""Guard the installed command surface against un-shipped entry points."""

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


if __name__ == "__main__":
    unittest.main()
