"""Strict JSON stream reads must consume EOF, not merely one valid prefix."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from constitutional_agent_testbench.cli import main
from constitutional_agent_testbench.common import JsonInputError, load_json_stream


class ShortReadStream:
    def __init__(self, payload, chunk_size):
        self.source = io.BytesIO(payload) if isinstance(payload, bytes) else io.StringIO(payload)
        self.chunk_size = chunk_size
        self.requests = []

    def read(self, size):
        self.requests.append(size)
        return self.source.read(min(size, self.chunk_size))


class JsonStreamReadTests(unittest.TestCase):
    def test_short_reads_reassemble_binary_and_text_json(self):
        expected = {"note": "synthetic-雪💡"}
        document = json.dumps(expected, ensure_ascii=False)
        for payload in (document, document.encode("utf-8")):
            for chunk_size in (1, 3, 8):
                with self.subTest(binary=isinstance(payload, bytes), chunk_size=chunk_size):
                    self.assertEqual(load_json_stream(ShortReadStream(payload, chunk_size)), expected)

    def test_valid_prefix_does_not_hide_trailing_data(self):
        for payload in ('{}{}', '{} trailing', '{}\xff'):
            for document in (payload, payload.encode("utf-8")):
                with self.subTest(document=document):
                    with self.assertRaises(JsonInputError):
                        load_json_stream(ShortReadStream(document, 2))

    def test_short_reads_enforce_the_cumulative_byte_limit(self):
        for document in ('{}' + ' ' * 14, b'{}' + b' ' * 14):
            with self.subTest(document=document), patch(
                "constitutional_agent_testbench.common.MAX_JSON_INPUT_BYTES", 8
            ):
                stream = ShortReadStream(document, 2)
                with self.assertRaisesRegex(JsonInputError, "file-size limit"):
                    load_json_stream(stream)
                self.assertEqual(stream.source.tell(), 9)
                self.assertEqual(stream.requests, [9, 7, 5, 3, 1])

    def test_exact_byte_limit_still_requires_eof(self):
        for document in ('{"a":"雪"}', '{"a":"雪"}'.encode("utf-8")):
            with self.subTest(document=document), patch(
                "constitutional_agent_testbench.common.MAX_JSON_INPUT_BYTES", 11
            ):
                self.assertEqual(load_json_stream(ShortReadStream(document, 2)), {"a": "雪"})

    def test_read_failure_after_valid_prefix_is_not_ignored(self):
        for error in (OSError("synthetic read failure"), UnicodeError("synthetic encoding failure")):
            stream = Mock()
            stream.read.side_effect = [b"{}", error]
            with self.subTest(error=type(error).__name__), self.assertRaises(JsonInputError):
                load_json_stream(stream)

    def test_invalid_or_inconsistent_read_types_fail_closed(self):
        for chunks in ([b"{}", ""], ["{}", b""], [b"{}", None], ["{}", 1]):
            stream = Mock()
            stream.read.side_effect = chunks
            with self.subTest(chunks=chunks), self.assertRaises(JsonInputError):
                load_json_stream(stream)

    def test_split_encoding_errors_and_multibyte_limits(self):
        for payload in (b"\xef\xbb\xbf{}", b"{}\xff", "\ufeff{}", "{}\ud800"):
            with self.subTest(payload=payload), self.assertRaises(JsonInputError):
                load_json_stream(ShortReadStream(payload, 1))
        for payload in ('"💡💡"', '"💡💡"'.encode("utf-8")):
            with self.subTest(payload=payload), patch(
                "constitutional_agent_testbench.common.MAX_JSON_INPUT_BYTES", 8
            ), self.assertRaisesRegex(JsonInputError, "file-size limit"):
                load_json_stream(ShortReadStream(payload, 2))

    def test_short_reading_stdin_rejects_a_second_document(self):
        policy = '{"schema_version":"1.0","policy_id":"test","rules":[{"rule_id":"r","kind":"false","path":"blocked"}]}'
        for payload in (policy, policy.encode("utf-8")):
            stream = ShortReadStream(payload + (b"{}" if isinstance(payload, bytes) else "{}"), len(payload))
            stdin = SimpleNamespace(buffer=stream) if isinstance(payload, bytes) else stream
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(binary=isinstance(payload, bytes)), patch("sys.stdin", stdin), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["validate-policy", "-"])
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(json.loads(stderr.getvalue())["error"]["code"], "INVALID_JSON_INPUT")


if __name__ == "__main__":
    unittest.main()
