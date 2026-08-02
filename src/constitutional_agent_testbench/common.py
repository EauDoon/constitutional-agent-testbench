"""Shared JSON, path, and error helpers."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


MAX_JSON_INPUT_BYTES = 1_000_000
MAX_JSON_NESTING = 32
MAX_JSON_NODES = 100_000


class TestbenchError(Exception):
    """Base class for controlled public errors."""

    code = "TESTBENCH_ERROR"


class JsonInputError(TestbenchError):
    """Raised when an input file cannot be decoded as strict JSON."""

    code = "INVALID_JSON_INPUT"


class JsonOutputError(TestbenchError):
    """Raised when an output file cannot be written."""

    code = "JSON_OUTPUT_ERROR"


def _reject_non_finite(token: str) -> None:
    raise ValueError("Non-finite JSON number is not supported.")


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object members are not supported.")
        result[key] = value
    return result


def load_json(path: str | Path) -> Any:
    """Load strict UTF-8 JSON without echoing paths or input content in errors."""

    try:
        with Path(path).open("rb") as input_file:
            data = input_file.read(MAX_JSON_INPUT_BYTES + 1)
    except OSError as exc:
        raise JsonInputError("Unable to read the requested JSON input.") from exc

    if len(data) > MAX_JSON_INPUT_BYTES:
        raise JsonInputError(
            "The requested input exceeds the 1,000,000-byte file-size limit."
        )

    try:
        text = data.decode("utf-8")
    except UnicodeError as exc:
        raise JsonInputError("Unable to read the requested JSON input.") from exc

    return parse_json_text(text)


def parse_json_text(text: str) -> Any:
    """Parse bounded strict JSON supplied directly by a local editor."""

    if len(text.encode("utf-8")) > MAX_JSON_INPUT_BYTES:
        raise JsonInputError(
            "The requested input exceeds the 1,000,000-byte file-size limit."
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise JsonInputError("The requested input is not valid strict JSON.") from exc

    try:
        ensure_json_value(value, label="JSON input")
    except ValueError as exc:
        raise JsonInputError(
            "The requested input exceeds supported JSON structural limits."
        ) from exc
    return value


def stable_json(value: Any) -> str:
    """Serialize a JSON-compatible value in one stable public format."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def write_json(path: str | Path, value: Any) -> None:
    """Write stable UTF-8 JSON to an explicitly requested destination."""

    destination = Path(path)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(stable_json(value), encoding="utf-8", newline="\n")
    except (OSError, OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise JsonOutputError("Unable to write the requested JSON output.") from exc


def ensure_json_value(value: Any, *, label: str) -> None:
    """Reject non-portable or structurally unbounded JSON values."""

    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, container_depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise ValueError(f"{label} exceeds the {MAX_JSON_NODES}-node limit.")

        if current is None or isinstance(current, (bool, str)):
            continue
        if isinstance(current, int) and not isinstance(current, bool):
            continue
        if isinstance(current, float):
            if math.isfinite(current):
                continue
            raise ValueError(f"{label} contains a non-finite number.")

        next_depth = container_depth + 1
        if next_depth > MAX_JSON_NESTING:
            raise ValueError(
                f"{label} exceeds the {MAX_JSON_NESTING}-level nesting limit."
            )
        if isinstance(current, list):
            stack.extend((item, next_depth) for item in current)
            continue
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError(
                        f"{label} contains a non-string object key."
                    )
                stack.append((item, next_depth))
            continue
        raise ValueError(f"{label} contains a value that JSON cannot represent.")


def canonical_json(value: Any) -> str:
    """Return a compact canonical form used for strict JSON equality."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def bounded_canonical_json_size(value: Any, *, label: str, limit: int) -> int:
    """Measure canonical UTF-8 JSON incrementally and fail above ``limit``.

    ``JSONEncoder.iterencode`` avoids constructing one complete serialized copy
    merely to enforce an in-memory boundary. Structural validation remains the
    caller's responsibility.
    """

    encoder = json.JSONEncoder(
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    total = 0
    try:
        for chunk in encoder.iterencode(value):
            total += len(chunk.encode("utf-8"))
            if total > limit:
                raise ValueError(f"{label} exceeds the {limit}-byte limit.")
    except (OverflowError, RecursionError, TypeError) as exc:
        raise ValueError(f"{label} is not strict JSON.") from exc
    return total


def json_values_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool and integer equivalence."""

    try:
        return canonical_json(left) == canonical_json(right)
    except (OverflowError, RecursionError, TypeError, ValueError):
        return False


def get_field(document: dict[str, Any], path: str) -> tuple[bool, Any]:
    """Resolve a validated dot-separated path through JSON objects."""

    current: Any = document
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return False, None
        current = current[segment]
    return True, current
