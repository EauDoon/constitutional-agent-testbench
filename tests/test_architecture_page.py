"""Confirm that the offline graph and evidence still describe this checkout."""
import subprocess
import sys
import unittest
from pathlib import Path


class ArchitecturePageTests(unittest.TestCase):
    def test_generated_snapshot_is_current(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "refresh_architecture.py"
        subprocess.run([sys.executable, str(script), "--check"], check=True)
