"""Check that every package version surface agrees before a release.

The single source is ``src/constitutional_agent_testbench/_version.py``. This
script reads it with ``ast`` and never imports the package, so it works from a
checkout, an unpacked source distribution or a release job before installation.
It uses only the standard library and reads every file as UTF-8.

Checks:

1. ``__version__`` is ``X.Y.Z`` and ``pyproject.toml`` declares no static version.
2. ``CHANGELOG.md`` has ``## [Unreleased]`` above the first release heading, and
   that heading is ``## [X.Y.Z] - YYYY-MM-DD`` for this version.
3. ``release/vX.Y.Z-manifest.json`` names this version, both artifact file names,
   ``requires-python`` and the pinned build backend from ``pyproject.toml``.
4. ``README.md`` states ``Current package version: **X.Y.Z**``.
5. With ``--tag``, the tag is exactly ``vX.Y.Z``.

Exit 0 when everything agrees. Exit 1 prints every mismatch, one per line, on
standard error. ``--print-version`` prints the version; ``--release-notes``
prints the body of this version's changelog section. Package and schema
versions are independent; nothing here reads or changes a schema version.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = Path("src") / "constitutional_agent_testbench" / "_version.py"
DIST_STEM = "constitutional_agent_testbench"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
UNRELEASED_HEADING = "## [Unreleased]"
RELEASE_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$")
LINK_REFERENCE = re.compile(r"^\[[^\]]+\]: \S+")


class VersionSourceError(Exception):
    """Raised when the version source itself cannot be read."""


def read_version(root: Path) -> str:
    """Return the ``__version__`` string literal assigned in _version.py."""

    path = root / VERSION_FILE
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise VersionSourceError(f"{VERSION_FILE.as_posix()} cannot be read: {exc}") from exc
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__version__"
                   for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
        raise VersionSourceError(f"{VERSION_FILE.as_posix()} must assign __version__ a string literal")
    raise VersionSourceError(f"{VERSION_FILE.as_posix()} does not assign __version__")


def artifact_names(version: str) -> list[str]:
    return [f"{DIST_STEM}-{version}-py3-none-any.whl", f"{DIST_STEM}-{version}.tar.gz"]


def _read_text(root: Path, name: str, problems: list[str]) -> str | None:
    try:
        return (root / name).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        problems.append(f"{name} cannot be read: {exc.__class__.__name__}")
        return None


def _check_changelog(text: str, version: str, problems: list[str]) -> None:
    lines = text.splitlines()
    try:
        unreleased = lines.index(UNRELEASED_HEADING)
    except ValueError:
        problems.append(f"CHANGELOG.md has no '{UNRELEASED_HEADING}' heading")
        unreleased = None
    release_index = next(
        (index for index, line in enumerate(lines)
         if line.startswith("## [") and line != UNRELEASED_HEADING),
        None,
    )
    if release_index is None:
        problems.append("CHANGELOG.md has no release heading")
        return
    heading = lines[release_index]
    match = RELEASE_HEADING.match(heading)
    if match is None:
        problems.append(
            f"CHANGELOG.md first release heading {heading!r} is not '## [X.Y.Z] - YYYY-MM-DD'"
        )
    elif match.group(1) != version:
        problems.append(
            f"CHANGELOG.md first release is {match.group(1)}, but _version.py is {version}"
        )
    if unreleased is not None and unreleased > release_index:
        problems.append(f"CHANGELOG.md '{UNRELEASED_HEADING}' must precede the first release")


def _check_manifest(root: Path, version: str, pyproject: dict, problems: list[str]) -> None:
    name = f"release/v{version}-manifest.json"
    text = _read_text(root, name, problems)
    if text is None:
        return
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError:
        problems.append(f"{name} is not valid JSON")
        return
    if not isinstance(manifest, dict):
        problems.append(f"{name} must be a JSON object")
        return
    expected = {
        "version": version,
        "artifacts": artifact_names(version),
        "python": pyproject.get("project", {}).get("requires-python"),
        "build_backend": (pyproject.get("build-system", {}).get("requires") or [None])[0],
    }
    for field, wanted in expected.items():
        if manifest.get(field) != wanted:
            problems.append(f"{name} {field} is {manifest.get(field)!r}, expected {wanted!r}")


def check(root: Path, tag: str | None = None) -> tuple[str, list[str]]:
    """Return the version and every mismatch found under ``root``."""

    version = read_version(root)
    problems: list[str] = []
    if not SEMVER.match(version):
        problems.append(f"{VERSION_FILE.as_posix()} version {version!r} is not X.Y.Z")

    pyproject: dict = {}
    pyproject_text = _read_text(root, "pyproject.toml", problems)
    if pyproject_text is not None:
        try:
            pyproject = tomllib.loads(pyproject_text)
        except tomllib.TOMLDecodeError:
            problems.append("pyproject.toml is not valid TOML")
    project = pyproject.get("project", {})
    if "version" in project:
        problems.append("pyproject.toml sets a static version; it must read _version.py")
    if "version" not in project.get("dynamic", []) and pyproject:
        problems.append("pyproject.toml does not declare the version as dynamic")

    changelog = _read_text(root, "CHANGELOG.md", problems)
    if changelog is not None:
        _check_changelog(changelog, version, problems)

    _check_manifest(root, version, pyproject, problems)

    readme = _read_text(root, "README.md", problems)
    expected_line = f"Current package version: **{version}**"
    if readme is not None and expected_line not in readme:
        problems.append(f"README.md does not state '{expected_line}'")

    if tag is not None and tag != f"v{version}":
        problems.append(f"tag {tag!r} does not match version v{version}")
    return version, problems


def release_notes(root: Path, version: str) -> str:
    """Return the body of the ``## [version]`` changelog section."""

    lines = (root / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    prefix = f"## [{version}]"
    start = next((index for index, line in enumerate(lines)
                  if line == prefix or line.startswith(prefix + " - ")), None)
    if start is None:
        raise VersionSourceError(f"CHANGELOG.md has no section for {version}")
    body: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("## ") or LINK_REFERENCE.match(line):
            break
        body.append(line)
    notes = "\n".join(body).strip()
    if not notes:
        raise VersionSourceError(f"CHANGELOG.md section for {version} is empty")
    return notes + "\n"


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Check that every package version surface agrees.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--tag", help="also require this release tag to equal v<version>")
    mode.add_argument("--print-version", action="store_true", help="print the version and exit")
    mode.add_argument("--release-notes", action="store_true",
                      help="print this version's CHANGELOG section body and exit")
    arguments = parser.parse_args(argv)
    try:
        if arguments.print_version:
            print(read_version(root))
            return 0
        if arguments.release_notes:
            sys.stdout.write(release_notes(root, read_version(root)))
            return 0
        version, problems = check(root, arguments.tag)
    except VersionSourceError as exc:
        print(exc, file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    suffix = f" and tag {arguments.tag}" if arguments.tag else ""
    print(f"version {version}: _version.py, CHANGELOG.md, release manifest and README.md agree{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
