# Author, curate, and replay a regression corpus

Version 0.4.0 adds corpus workflows to the unchanged policy schema 1.0 evaluator.
All commands run locally. No artifact selects a plugin, evaluator, file path,
shell command, network request, or model. Install with `pip install --no-deps .`.

## Run the complete workflow

```text
constitutional-agent-testbench inspect-policy examples/policy.json
constitutional-agent-testbench inspect-suite examples/assertion-suite.json --strict-exit
constitutional-agent-testbench run-suite examples/policy.json examples/assertion-suite.json --strict-exit
constitutional-agent-testbench triage-suite examples/policy.json examples/assertion-suite.json --strict-exit
constitutional-agent-testbench select-suite examples/assertion-suite.json examples/case-selection.json --output focused.json
constitutional-agent-testbench reduce-suite examples/policy.json examples/assertion-suite.json --output reduced.json
constitutional-agent-testbench create-suite-receipt examples/policy.json reduced.json --output suite-receipt.json
constitutional-agent-testbench verify-suite-receipt examples/policy.json reduced.json suite-receipt.json --strict-exit
constitutional-agent-testbench create-replay examples/policy.json reduced.json --output replay.json
constitutional-agent-testbench replay replay.json --strict-exit
```

`merge-suites LEFT RIGHT --output combined.json` appends same-version corpora in
input order. Duplicate IDs fail instead of silently dropping, overwriting or
renaming cases. `select-suite` accepts a JSON array of exact IDs, rejects unknown
or duplicate IDs and empty selections, and preserves original case order.

## Assertions and diagnostics

Suite 1.0 remains unchanged. Suite 1.1 adds optional `expected_rules` per case:

```json
{"decision-accepted": {"passed": false, "reason_code": "FIELD_MISSING"}}
```

Both assertion fields are required. Valid reason codes are the evaluator's public
codes, and `passed` is true exactly when `reason_code` is `RULE_SATISFIED`.
Unspecified rules are not asserted. An absent asserted rule is a mismatch, so a
policy migration cannot silently remove an assertion. Expected overall failure
can therefore fail regression when it occurs for the wrong reason.

`inspect-policy` reports kind counts, paths and ancestor relationships for up to
256 rules. `inspect-suite` groups identical canonical responses; incompatible
expected verdicts or overlapping rule assertions are conflicts. Compatible
partial assertions remain compatible. Boolean and numeric values stay distinct.
Neither inspection report copies constraint or response values.

`triage-suite` lists only expectation mismatches, including unexpected passes,
and groups actual failures by rule, path and reason. `reduce-suite` greedily
retains every observed rule/outcome/reason, explicit rule assertion, and verdict/expectation category,
plus every mismatching case. Ties use source order; output retains source order.
It supports up to 256 rules. It is not guaranteed to find the smallest corpus,
preserve case frequencies, or cover unseen inputs.

## Replay and data boundaries

Suite receipts bind canonical policy, complete fixtures, case order, assertions,
and every evaluation result. Verification recomputes all bindings. Replay bundles
contain policy, suite and receipt together; they never fetch external inputs.
`verified` means consistent bindings. `replay_passed` additionally requires
matching regression expectations. If verification fails, `matches_expectations`
is null and the stored report is not treated as trustworthy.

Inspection, triage and replay reports omit raw candidate values. **Merged,
selected and reduced suites and replay bundles contain original response values.**
Receipts omit values but hashes can reveal equality or allow low-entropy guessing.
Anyone with the inputs can generate these artifacts; they are not signatures,
independent observations, proofs of safety, or evidence of real model behavior.

Workflow artifacts must fit 1,000,000 formatted UTF-8 bytes, 32 nesting levels
and 100,000 nodes. Bundling adds nesting and bytes, so separate valid inputs may
not fit together. Existing suites retain the 256-case and 32,000,000 policy-byte
evaluation-work limits. Oversized workflows fail closed, never silently sample.

## Files and automation

All JSON commands accept `--output PATH`; playground retains its explicit export
dialog. Output is serialized before opening a destination and atomically replaces
an existing file only after the temporary write succeeds. The prior file survives
write/replace errors. This is atomic replacement, not a cross-filesystem backup or
power-loss guarantee. Output paths equal to an input, including resolved and
hard-link aliases, are rejected before any JSON input is read. `--output -` is
invalid. These local preflight checks do not provide a sandbox against a separate
process concurrently changing paths or directories.

Without `--output`, commands print JSON. With it, they print a path-free
acknowledgment while retaining the original computation's strict exit status.
At most one JSON input per invocation may be `-` (stdin).

Default exit 0 means a completed computation. `--strict-exit` on `inspect-suite`
requires consistent expectations; `triage-suite` requires matching expectations;
`verify-suite-receipt` requires consistent bindings; `replay` requires both.
Valid negative results return 1 and malformed inputs or exceeded bounds return 2.
Existing commands preserve their prior strict-exit semantics.
