from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from constitutional_agent_testbench.cli import main


class StdinTrap:
    reads = 0

    @property
    def buffer(self):
        type(self).reads += 1
        raise RuntimeError("standard input was read")


class CliOutputGuardTests(unittest.TestCase):
    def test_rejects_output_dash_before_reading_policy_input(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        stdin = StdinTrap()
        StdinTrap.reads = 0

        with (
            patch.object(sys, "stdin", stdin),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = main(["generate-synthetic", "-", "--output", "-"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(StdinTrap.reads, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {
                "error": {
                    "code": "INVALID_COMMAND",
                    "message": (
                        "generate-synthetic --output writes a file and does not "
                        "accept '-'."
                    ),
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
