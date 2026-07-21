"""Shared JSON, path, and error helpers."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


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
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise JsonInputError("Unable to read the requested JSON input.") from exc

    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise JsonInputError("The requested input is not valid strict JSON.") from exc


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
    """Reject values that are not portable JSON values."""

    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise ValueError(f"{label} contains a non-finite number.")
    if isinstance(value, list):
        for item in value:
            ensure_json_value(item, label=label)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{label} contains a non-string object key.")
            ensure_json_value(item, label=label)
        return
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
