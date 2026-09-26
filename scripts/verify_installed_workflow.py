"""Exercise an installed console command in a fresh directory with synthetic data.

Run using the Python interpreter whose environment contains the installed package.
No source-tree imports, network, models, or persistent fixtures are used.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile


MARKER = "SYNTHETIC_PRIVATE_é雪💡"


def main():
    executable = Path(sysconfig.get_path("scripts")) / (
        "constitutional-agent-testbench.exe" if os.name == "nt" else "constitutional-agent-testbench"
    )
    if not executable.is_file():
        raise RuntimeError("Install the package into this interpreter's environment first.")
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    steps = []
    with tempfile.TemporaryDirectory(prefix="cat-adopter-") as directory:
        root = Path(directory)

        def save(name, value):
            (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

        def run(*arguments, expected=0, encoding="ascii:replace", stdin=None, values=False):
            result = subprocess.run(
                [str(executable), *arguments], cwd=root,
                env={**environment, "PYTHONIOENCODING": encoding},
                input=stdin, capture_output=True, timeout=30,
            )
            if result.returncode != expected:
                raise AssertionError(f"{arguments[0]}: expected exit {expected}, got {result.returncode}")
            data = result.stderr if expected == 2 else result.stdout
            if (result.stdout if expected == 2 else result.stderr):
                raise AssertionError(f"{arguments[0]}: unexpected output stream")
            report = json.loads(data.decode("utf-8"))
            if not values and MARKER in data.decode("utf-8"):
                raise AssertionError(f"{arguments[0]} exposed a response value")
            steps.append({"command": arguments[0], "exit": result.returncode, "encoding": encoding})
            return report, data

        # Verify the import and command come from the installation, not this checkout.
        probe = subprocess.run(
            [sys.executable, "-c",
             "import json, importlib.metadata as m, constitutional_agent_testbench as c; "
             "d=m.distribution('constitutional-agent-testbench'); "
             "print(json.dumps({'module':c.__file__, "
             "'source':json.loads(d.read_text('direct_url.json') or '{}')}))"],
            cwd=root, env={**environment, "PYTHONIOENCODING": "utf-8"},
            capture_output=True, check=True, timeout=30,
        )
        checkout = Path(__file__).resolve().parents[1]
        installation = json.loads(probe.stdout.decode("utf-8"))
        if (installation["source"].get("dir_info", {}).get("editable") is True
                or Path(installation["module"]).resolve().is_relative_to(checkout / "src")):
            raise AssertionError("Expected a non-editable installed distribution.")

        policy = {"schema_version": "1.0", "policy_id": "synthetic-adopter", "rules": [
            {"rule_id": "execute", "kind": "false", "path": "action.execute"},
            {"rule_id": "notes", "kind": "empty_list", "path": "audit.notes"}]}
        cases = []
        for identifier, action, reason in (
            ("unicode-pass", {"execute": False}, "RULE_SATISFIED"),
            ("missing-field", {}, "FIELD_MISSING"),
            ("numeric-zero", {"execute": 0}, "VALUE_NOT_FALSE"),
            ("nonobject-parent", None, "FIELD_MISSING"),
        ):
            passed = reason == "RULE_SATISFIED"
            cases.append({"case_id": identifier,
                "response": {"action": action, "audit": {"notes": []}, "note": MARKER},
                "expected_passed": passed, "expected_rules": {
                    "execute": {"passed": passed, "reason_code": reason},
                    "notes": {"passed": True, "reason_code": "RULE_SATISFIED"}}})
        suite = {"suite_version": "1.1", "cases": cases}
        candidate = copy.deepcopy(policy)
        candidate["rules"][0].update(kind="equals", value=False)
        save("policy.json", policy)
        save("candidate.json", candidate)
        save("suite.json", suite)
        run("validate-policy", "policy.json")
        run("validate-suite", "suite.json")
        run("check-suite", "policy.json", "suite.json", "--strict-exit")
        comparison, _ = run("compare-policies", "policy.json", "candidate.json", "suite.json",
                            "--strict-exit", expected=1)
        assert comparison["verdict_change_count"] == 0
        assert comparison["after_matches_expectations"] is False
        migration, _ = run("migration-expectations", "policy.json", "candidate.json", "suite.json",
                           "--strict-exit", expected=1)
        assert migration["regressions"] == ["numeric-zero"]
        run("create-suite-receipt", "policy.json", "suite.json", "--output", "receipt.json")
        assert MARKER not in (root / "receipt.json").read_text(encoding="utf-8")
        run("verify-suite-receipt", "policy.json", "suite.json", "receipt.json", "--strict-exit")
        run("create-replay", "policy.json", "suite.json", "--output", "exported.json")
        exported = (root / "exported.json").read_bytes()

        # Stdout redirection, explicit export and repeated invocations must agree byte-for-byte.
        for encoding in ("utf-8", "ascii", "ascii:replace", "ascii:ignore", "latin-1:replace", "utf-16"):
            bundle, serialized = run("create-replay", "policy.json", "suite.json", encoding=encoding, values=True)
            assert bundle["suite"] == suite
            assert serialized == exported
            (root / "portable.json").write_bytes(serialized)
            replay, _ = run("replay", "portable.json", "--strict-exit", encoding=encoding)
            assert replay["verified"] is True and replay["replay_passed"] is True
        _, repeated = run("create-replay", "policy.json", "suite.json", values=True)
        assert repeated == exported
        run("replay", "-", "--strict-exit", stdin=exported)

        # Neither changed assertion intent nor altered result fields may pass old evidence.
        bundle = json.loads(exported)
        for mutate in (
            lambda b: b["suite"]["cases"][2]["expected_rules"]["execute"].update(reason_code="VALUE_NOT_EQUAL"),
            lambda b: b["suite"]["cases"][0].pop("expected_rules"),
            lambda b: b["suite"]["cases"].reverse(),
            lambda b: b["receipt"]["evaluation"].update(matches_expectations=1),
            lambda b: b["receipt"]["evaluation"]["cases"][0]["evaluation"]["rule_results"][0].update(reason_code="FIELD_MISSING"),
            lambda b: b["receipt"]["evaluation"]["cases"][0]["rule_assertion_mismatches"].append("execute"),
        ):
            tampered = copy.deepcopy(bundle)
            mutate(tampered)
            save("tampered.json", tampered)
            report, _ = run("replay", "tampered.json", "--strict-exit", expected=1)
            assert report["verified"] is False and report["matches_expectations"] is None
            assert report["replay_passed"] is False
            # Exporting a failing result must retain the negative strict exit.
            run("replay", "tampered.json", "--strict-exit", "--output", "negative.json", expected=1)

        # A freshly recomputed receipt can be consistent while its assertions fail.
        bad_suite = copy.deepcopy(suite)
        bad_suite["cases"][2]["expected_rules"]["execute"]["reason_code"] = "VALUE_NOT_EQUAL"
        save("regression.json", bad_suite)
        run("create-replay", "policy.json", "regression.json", "--output", "regression-replay.json")
        report, _ = run("replay", "regression-replay.json", "--strict-exit", expected=1)
        assert report["verified"] is True and report["matches_expectations"] is False

        # Strict JSON and export guards stay fail-closed, retaining existing files.
        previous = (root / "exported.json").read_bytes()
        for malformed in (b'{"suite_version":"1.1","suite_version":"1.1","cases":[]}', b'{"x":NaN}'):
            run("validate-suite", "-", "--output", "exported.json", stdin=malformed, expected=2)
            assert (root / "exported.json").read_bytes() == previous
        bad_suite["cases"][0]["expected_passed"] = 1
        save("invalid.json", bad_suite)
        run("validate-suite", "invalid.json", expected=2)
        run("replay", "absent.json", "--output", "exported.json", expected=2)
        assert (root / "exported.json").read_bytes() == previous
        source = (root / "suite.json").read_bytes()
        run("create-replay", "policy.json", "suite.json", "--output", "suite.json", expected=2)
        assert (root / "suite.json").read_bytes() == source

    print(json.dumps({"passed": True, "fixture_kind": "synthetic", "values_included": False,
                      "command_checks": len(steps), "steps": steps}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
