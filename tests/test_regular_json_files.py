"""File inputs cannot block on named pipes or read device streams."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from constitutional_agent_testbench.common import JsonInputError, load_json


class RegularJsonFileTests(unittest.TestCase):
    def test_regular_and_symlink_inputs_remain_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text('{"value":"雪"}', encoding="utf-8")
            self.assertEqual(load_json(path), {"value": "雪"})
            if hasattr(os, "symlink"):
                link = Path(folder) / "link.json"
                try:
                    link.symlink_to(path)
                except OSError:
                    return  # Some Windows accounts cannot create symlinks.
                self.assertEqual(load_json(link), {"value": "雪"})

    def test_nonfiles_and_missing_files_are_controlled_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            for path in (folder, Path(folder) / "absent.json"):
                with self.subTest(path=path), self.assertRaises(JsonInputError):
                    load_json(path)

    def test_oversized_files_are_rejected_before_stream_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_bytes(b'{}' + b' ' * 10)
            with patch("constitutional_agent_testbench.common.MAX_JSON_INPUT_BYTES", 8), \
                 patch("constitutional_agent_testbench.common.load_json_stream") as read:
                with self.assertRaisesRegex(JsonInputError, "file-size limit"):
                    load_json(path)
                read.assert_not_called()

    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"), "POSIX named pipes required")
    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.pipe"
            os.mkfifo(path)
            result = subprocess.run(
                [sys.executable, "-c", "from constitutional_agent_testbench.common import load_json, JsonInputError\n"
                 "import sys\ntry: load_json(sys.argv[1])\nexcept JsonInputError: sys.exit(0)\n"
                 "sys.exit(1)", str(path)],
                timeout=5, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
