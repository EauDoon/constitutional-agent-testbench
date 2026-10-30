"""Shared bounded artifact contract for optional corpus workflows."""
from typing import TypeVar

from .common import MAX_JSON_INPUT_BYTES, TestbenchError, ensure_json_value, stable_json


class WorkflowInputError(TestbenchError):
    code = "INVALID_WORKFLOW"


_T = TypeVar("_T")


def bounded_artifact(value: _T) -> _T:
    try:
        ensure_json_value(value, label="Workflow artifact")
        if len(stable_json(value).encode("utf-8")) > MAX_JSON_INPUT_BYTES:
            raise ValueError()
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise WorkflowInputError("Workflow artifact exceeds strict JSON limits.") from exc
    return value
