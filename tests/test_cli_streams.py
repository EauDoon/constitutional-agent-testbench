"""JSON process streams must preserve portable evidence regardless of locale."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from constitutional_agent_testbench import cli
from constitutional_agent_testbench.cli import main
from constitutional_agent_testbench.common import stable_json
from constitutional_agent_testbench.replay import create_replay_bundle, replay_bundle


class JsonStreamTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = {"schema_version": "1.0", "policy_id": "synthetic", "rules": [
            {"rule_id": "r", "kind": "false", "path": "action"}]}
        self.suite = {"suite_version": "1.1", "cases": [{
            "case_id": "unicode", "response": {"action": False, "note": "SYNTHETIC_é雪💡"},
            "expected_passed": True,
            "expected_rules": {"r": {"passed": True, "reason_code": "RULE_SATISFIED"}}}]}
        self.policy_path = self.root / "policy.json"
        self.policy_path.write_text(stable_json(self.policy), encoding="utf-8")

    def test_stdout_preserves_unicode_and_lf_independent_of_text_encoding(self):
        expected = stable_json(create_replay_bundle(self.policy, self.suite)).encode("utf-8")
        for encoding, errors in (("ascii", "strict"), ("ascii", "replace"),
                                 ("ascii", "ignore"), ("latin-1", "replace"),
                                 ("utf-16", "strict")):
            with self.subTest(encoding=encoding, errors=errors):
                buffer = io.BytesIO()
                with io.TextIOWrapper(buffer, encoding=encoding, errors=errors, newline="\r\n") as stdout:
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr), patch(
                        "sys.stdin", io.StringIO(stable_json(self.suite))
                    ):
                        code = main(["create-replay", str(self.policy_path), "-"])
                    self.assertEqual(code, 0)
                    self.assertEqual(stderr.getvalue(), "")
                    self.assertEqual(buffer.getvalue(), expected)
                    self.assertTrue(replay_bundle(json.loads(buffer.getvalue()))["replay_passed"])

    def test_text_only_embedding_retains_complete_unicode(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), patch("sys.stdin", io.StringIO(stable_json(self.suite))):
            code = main(["create-replay", str(self.policy_path), "-"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), create_replay_bundle(self.policy, self.suite))

    def test_stderr_is_utf8_json_even_for_nonascii_validation_diagnostics(self):
        malformed = dict(self.policy, **{"SYNTHETIC_雪": True})
        buffer = io.BytesIO()
        with io.TextIOWrapper(buffer, encoding="ascii", errors="replace", newline="\r\n") as stderr:
            stdout = io.StringIO()
            with redirect_stderr(stderr), redirect_stdout(stdout), patch(
                "sys.stdin", io.StringIO(stable_json(malformed))
            ):
                code = main(["validate-policy", "-"])
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            error = json.loads(buffer.getvalue().decode("utf-8"))
            self.assertEqual(error["error"]["code"], "INVALID_POLICY")
            self.assertIn("SYNTHETIC_雪", error["error"]["message"])
            self.assertNotIn(b"\r", buffer.getvalue())


class ClosedStreamTests(unittest.TestCase):
    """A closed process stream is a controlled error, never a negative verdict.

    With --strict-exit, 1 means a valid negative result. Python sets a standard
    stream to None when its descriptor is closed at startup (`<&-`, `>&-`).
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.policy_path = root / "policy.json"
        self.policy_path.write_text(stable_json({
            "schema_version": "1.0", "policy_id": "synthetic",
            "rules": [{"rule_id": "r", "kind": "false", "path": "action"}]}), encoding="utf-8")

    def test_closed_standard_input_is_invalid_input(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), patch("sys.stdin", None):
            code = main(["evaluate", str(self.policy_path), "-", "--strict-exit"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(json.loads(stderr.getvalue())["error"]["code"], "INVALID_JSON_INPUT")

    def passing_evaluation(self):
        response_path = self.policy_path.with_name("response.json")
        response_path.write_text(stable_json({"action": False}), encoding="utf-8")
        return ["evaluate", str(self.policy_path), str(response_path), "--strict-exit"]

    def test_closed_or_failing_standard_output_is_an_output_error(self):
        # A write to a closed file object raises ValueError. The stream itself
        # stays open here: Python 3.14 argparse probes sys.stdout for colour
        # support, and a closed object would fail there before any write.
        for label, stdout in (("closed descriptor", None),
                              ("closed file object", _FailingStream(ValueError("I/O operation on closed file."))),
                              ("broken pipe", _FailingStream(BrokenPipeError(32, "Broken pipe"))),
                              ("device full", _FailingStream(OSError(28, "No space left")))):
            with self.subTest(stdout=label):
                stderr = io.StringIO()
                with patch("sys.stdout", stdout), redirect_stderr(stderr):
                    code = main(self.passing_evaluation())
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(stderr.getvalue()), {"error": {
                    "code": "JSON_OUTPUT_ERROR",
                    "message": "Unable to write the JSON result to standard output."}})

    def test_unwritable_standard_error_still_exits_2(self):
        for label, stderr in (("closed descriptor", None),
                              ("broken pipe", _FailingStream(BrokenPipeError(32, "Broken pipe")))):
            with self.subTest(stderr=label):
                stdout = io.StringIO()
                with redirect_stdout(stdout), patch("sys.stderr", stderr):
                    code = main(["validate-policy", str(self.policy_path.with_name("absent.json"))])
                self.assertEqual(code, 2)
                self.assertEqual(stdout.getvalue(), "")

    def test_unread_process_stdout_exits_2_with_only_a_json_error(self):
        # A pipe with no reader fails every write (EPIPE on POSIX, EINVAL on
        # Windows). The interpreter's exit-time flush must not then replace
        # exit status 2 with 120 or append a traceback.
        package_root = Path(cli.__file__).resolve().parents[1]
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(package_root), environment.get("PYTHONPATH"))))
        read_end, write_end = os.pipe()
        os.close(read_end)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "constitutional_agent_testbench", *self.passing_evaluation()],
                stdin=subprocess.DEVNULL, stdout=write_end, stderr=subprocess.PIPE,
                env=environment, timeout=60, check=False)
        finally:
            os.close(write_end)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stderr.decode("utf-8")), {"error": {
            "code": "JSON_OUTPUT_ERROR",
            "message": "Unable to write the JSON result to standard output."}})

    def test_only_a_failed_process_stream_is_redirected_to_the_null_device(self):
        released = self.policy_path.with_name("released.bin")
        untouched = self.policy_path.with_name("untouched.bin")
        descriptors = [os.open(path, os.O_WRONLY | os.O_CREAT) for path in (released, untouched)]
        try:
            process_stream, other_stream = (
                _FailingStream(BrokenPipeError(32, "Broken pipe"), descriptor=descriptor)
                for descriptor in descriptors)
            no_descriptor = _FailingStream(OSError(5, "I/O error"))
            with patch("sys.__stdout__", process_stream), patch("sys.__stderr__", no_descriptor):
                cli._release_failed_stream(process_stream)
                cli._release_failed_stream(other_stream)
                cli._release_failed_stream(no_descriptor)  # fileno() unsupported: ignored
                cli._release_failed_stream(None)
            for descriptor in descriptors:
                os.write(descriptor, b"written")
        finally:
            for descriptor in descriptors:
                os.close(descriptor)
        self.assertEqual(released.read_bytes(), b"")
        self.assertEqual(untouched.read_bytes(), b"written")


class _FailingStream(io.TextIOBase):
    """A text stream whose writes fail like a broken pipe or a full device."""

    def __init__(self, error, *, descriptor=None):
        self.error = error
        self.descriptor = descriptor

    def write(self, text):
        raise self.error

    def fileno(self):
        if self.descriptor is None:
            raise io.UnsupportedOperation("fileno")
        return self.descriptor


if __name__ == "__main__":
    unittest.main()
