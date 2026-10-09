"""Every package version surface must agree; scripts/check_version.py enforces it.

The script ships in the source distribution, so these checks also run from an
unpacked sdist, not only from a checkout.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_version.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_version", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


check_version = _load_script()


class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.version = check_version.read_version(ROOT)
        self.manifest = Path("release") / f"v{self.version}-manifest.json"
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.copy = Path(self._directory.name)
        for relative in (check_version.VERSION_FILE, Path("pyproject.toml"),
                         Path("CHANGELOG.md"), Path("README.md"), self.manifest):
            target = self.copy / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def edit(self, relative: Path | str, old: str, new: str) -> None:
        path = self.copy / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_bytes(text.replace(old, new, 1).encode("utf-8"))

    def problems(self, tag: str | None = None) -> list[str]:
        return check_version.check(self.copy, tag)[1]

    def run_main(self, *arguments: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = check_version.main(list(arguments), root=self.copy)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_repository_surfaces_agree(self) -> None:
        self.assertRegex(self.version, r"^\d+\.\d+\.\d+$")
        self.assertEqual(check_version.check(ROOT), (self.version, []))
        self.assertEqual(self.problems(), [])
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.run_main("--tag", f"v{self.version}")[0], 0)

    def test_changelog_heading_mismatch_is_named(self) -> None:
        self.edit("CHANGELOG.md", f"## [{self.version}] - ", "## [9.9.9] - ")
        problems = self.problems()
        self.assertTrue(any("CHANGELOG.md first release is 9.9.9" in item for item in problems))

    def test_changelog_needs_iso_dates_and_unreleased(self) -> None:
        self.edit("CHANGELOG.md", "## [Unreleased]\n", "## Unreleased\n")
        heading = next(line for line in (self.copy / "CHANGELOG.md").read_text(encoding="utf-8")
                       .splitlines() if line.startswith(f"## [{self.version}] - "))
        day = heading.rsplit(" - ", 1)[1]
        year, month, date = day.split("-")
        self.edit("CHANGELOG.md", heading, f"## [{self.version}] - {date}-{month}-{year}")
        problems = self.problems()
        self.assertTrue(any("'## [Unreleased]'" in item for item in problems))
        self.assertTrue(any("is not '## [X.Y.Z] - YYYY-MM-DD'" in item for item in problems))

    def test_manifest_mismatch_is_named(self) -> None:
        self.edit(self.manifest, f'"version": "{self.version}"', '"version": "9.9.9"')
        self.edit(self.manifest, '"python": ">=3.11"', '"python": ">=3.10"')
        problems = self.problems()
        name = self.manifest.as_posix()
        self.assertTrue(any(item.startswith(f"{name} version is '9.9.9'") for item in problems))
        self.assertTrue(any(item.startswith(f"{name} python is '>=3.10'") for item in problems))

    def test_missing_manifest_is_named(self) -> None:
        (self.copy / self.manifest).unlink()
        self.assertTrue(any(self.manifest.as_posix() in item for item in self.problems()))

    def test_readme_line_mismatch_is_named(self) -> None:
        self.edit("README.md", f"Current package version: **{self.version}**",
                  "Current package version: **9.9.9**")
        self.assertTrue(any(item.startswith("README.md does not state") for item in self.problems()))

    def test_static_pyproject_version_is_rejected(self) -> None:
        self.edit("pyproject.toml", 'dynamic = ["version"]\n', f'version = "{self.version}"\n')
        problems = self.problems()
        self.assertIn("pyproject.toml sets a static version; it must read _version.py", problems)
        self.assertIn("pyproject.toml does not declare the version as dynamic", problems)

    def test_wrong_tag_fails_with_one_line_per_mismatch(self) -> None:
        self.edit("README.md", f"Current package version: **{self.version}**",
                  "Current package version: **9.9.9**")
        code, stdout, stderr = self.run_main("--tag", "v9.9.9")
        self.assertEqual((code, stdout), (1, ""))
        lines = stderr.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn(f"tag 'v9.9.9' does not match version v{self.version}", lines)

    def test_print_version_and_release_notes(self) -> None:
        code, stdout, _ = self.run_main("--print-version")
        self.assertEqual((code, stdout.strip()), (0, self.version))
        code, notes, stderr = self.run_main("--release-notes")
        self.assertEqual((code, stderr), (0, ""))
        self.assertTrue(notes.strip())
        # Category headings (### Added) belong to the notes; the next release's
        # level-2 heading must not.
        self.assertNotRegex(notes, r"(?m)^## ")
        self.assertNotRegex(notes, r"(?m)^\[[^\]]+\]: ")

    def test_release_notes_stop_before_link_references(self) -> None:
        changelog = self.copy / "CHANGELOG.md"
        changelog.write_text(
            "# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-01-02\n\n### Added\n\n- One.\n\n"
            "[Unreleased]: https://example.invalid/compare/v1.2.3...HEAD\n"
            "[1.2.3]: https://example.invalid/releases/tag/v1.2.3\n",
            encoding="utf-8",
        )
        self.assertEqual(check_version.release_notes(self.copy, "1.2.3"), "### Added\n\n- One.\n")
        with self.assertRaises(check_version.VersionSourceError):
            check_version.release_notes(self.copy, "9.9.9")


if __name__ == "__main__":
    unittest.main()
