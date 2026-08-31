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


def format_verdict(result: dict[str, Any]) -> str:
    """Return a path-free pass/fail line that never copies candidate values."""

    rules = result["rule_results"]
    total = len(rules)
    if result["passed"]:
        return f"PASS — {total} of {total} rules satisfied"
    failed = [item for item in rules if not item["passed"]]
    details = ", ".join(
        f"{item['rule_id']}: {item['reason_code']}" for item in failed
    )
    return f"FAIL — {len(failed)} of {total} rules failed ({details})"


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
    root.geometry("900x720")

    def labeled_text(title: str, height: int, *, disabled: bool = False) -> Any:
        tk.Label(root, text=title, anchor="w").pack(fill="x", padx=8, pady=(8, 0))
        box = tk.Text(root, height=height, width=100)
        if disabled:
            box.configure(state="disabled")
        box.pack(fill="both", expand=True, padx=8)
        return box

    policy_box = labeled_text("Policy", 12)
    response_box = labeled_text("Response", 12)
    verdict_var = tk.StringVar(value="Idle — evaluate to see a live verdict")
    tk.Label(root, textvariable=verdict_var, anchor="w").pack(fill="x", padx=8, pady=(8, 0))
    result_box = labeled_text("Result", 8, disabled=True)
    policy_box.insert("1.0", stable_json(policy))
    response_box.insert("1.0", stable_json(response))

    def set_result(text: str) -> None:
        result_box.configure(state="normal")
        result_box.delete("1.0", "end")
        result_box.insert("1.0", text)
        result_box.configure(state="disabled")

    def evaluate() -> None:
        try:
            result = evaluate_documents(policy_box.get("1.0", "end"), response_box.get("1.0", "end"))
            verdict_var.set(format_verdict(result))
            set_result(stable_json(result))
        except (TestbenchError, ValueError, TypeError) as exc:
            verdict_var.set(f"INVALID — {exc}")
            set_result("")
            messagebox.showerror("Invalid input", str(exc))

    def export() -> None:
        try:
            result = evaluate_documents(policy_box.get("1.0", "end"), response_box.get("1.0", "end"))
            verdict_var.set(format_verdict(result))
            set_result(stable_json(result))
            target = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
            if target:
                write_json(target, result)
        except (TestbenchError, ValueError, TypeError) as exc:
            verdict_var.set(f"INVALID — {exc}")
            messagebox.showerror("Invalid input", str(exc))

    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=8, pady=8)
    tk.Button(buttons, text="Evaluate", command=evaluate).pack(side="left")
    tk.Button(buttons, text="Export result", command=export).pack(side="left")
    root.mainloop()
    return {"playground": "closed", "offline": True}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the playground console command and return a process exit code."""

    from .cli import main as cli_main

    arguments = list(sys.argv[1:] if argv is None else argv)
    return cli_main(["playground", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
