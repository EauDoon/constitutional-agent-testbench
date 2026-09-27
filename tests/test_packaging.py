"""Guard the installed command surface against un-shipped entry points."""

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src"


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


if __name__ == "__main__":
    unittest.main()