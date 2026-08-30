"""Small offline Tk policy playground with explicit export only."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

from .common import TestbenchError, load_json, parse_json_text, stable_json, write_json
from .evaluator import evaluate_response
from .policy import validate_policy


class PlaygroundUnavailableError(TestbenchError):
    """Raised when the optional Tk playground cannot open."""

    code = "PLAYGROUND_UNAVAILABLE"


def _load_optional(path: str | None, fallback: Any) -> Any:
    return load_json(path) if path else fallback


def evaluate_documents(policy_text: str, response_text: str) -> dict[str, Any]:
    """Evaluate editor text through the same strict boundaries as file input."""

    current_policy = validate_policy(parse_json_text(policy_text))
    current_response = parse_json_text(response_text)
    return evaluate_response(current_policy, current_response)


def run_playground(policy_path: str | None, response_path: str | None, *, smoke_test: bool = False) -> dict[str, Any]:
    default_policy = {
        "schema_version": "1.0",
        "policy_id": "playground",
        "rules": [{"rule_id": "decision-present", "kind": "required_field", "path": "decision"}],
    }
    default_response = {"decision": "demo"}
    if smoke_test:
        evaluate_response(
            _load_optional(policy_path, default_policy),
            _load_optional(response_path, default_response),
        )
        return {"playground": "ready", "offline": True, "export_requires_explicit_action": True}
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError as exc:
        raise PlaygroundUnavailableError(
            "The playground is unavailable because Tkinter is not installed."
        ) from exc

    policy = _load_optional(
        policy_path,
        default_policy,
    )
    response = _load_optional(response_path, default_response)
    validate_policy(policy)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise PlaygroundUnavailableError(
            "The playground could not open a window in this environment."
        ) from exc
    root.title("Constitutional Agent Testbench Playground")
    root.geometry("900x650")
    policy_box = tk.Text(root, height=14, width=100)
    response_box = tk.Text(root, height=14, width=100)
    result_box = tk.Text(root, height=8, width=100, state="disabled")
    policy_box.insert("1.0", stable_json(policy))
    response_box.insert("1.0", stable_json(response))
    policy_box.pack(fill="both", expand=True)
    response_box.pack(fill="both", expand=True)

    def evaluate() -> None:
        try:
            result = evaluate_documents(policy_box.get("1.0", "end"), response_box.get("1.0", "end"))
            result_box.configure(state="normal")
            result_box.delete("1.0", "end")
            result_box.insert("1.0", stable_json(result))
            result_box.configure(state="disabled")
        except (TestbenchError, ValueError, TypeError) as exc:
            messagebox.showerror("Invalid input", str(exc))

    def export() -> None:
        try:
            result = evaluate_documents(policy_box.get("1.0", "end"), response_box.get("1.0", "end"))
            target = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
            if target:
                write_json(target, result)
        except (TestbenchError, ValueError, TypeError) as exc:
            messagebox.showerror("Invalid input", str(exc))

    buttons = tk.Frame(root)
    buttons.pack(fill="x")
    tk.Button(buttons, text="Evaluate", command=evaluate).pack(side="left")
    tk.Button(buttons, text="Export result", command=export).pack(side="left")
    result_box.pack(fill="both", expand=True)
    root.mainloop()
    return {"playground": "closed", "offline": True}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the playground console command and return a process exit code."""

    from .cli import main as cli_main

    arguments = list(sys.argv[1:] if argv is None else argv)
    return cli_main(["playground", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
