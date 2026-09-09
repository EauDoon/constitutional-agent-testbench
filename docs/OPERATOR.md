# Local policy operator workflow

## Inspect declared policy structure

`select-suite SUITE SELECTION` creates a focused executable corpus from a JSON
array of exact case IDs. It preserves source order and rejects unknown IDs,
duplicates, or an empty selection. The result includes selected response values.
Use this to reproduce a named case without editing the original fixture file.

`merge-suites LEFT RIGHT` appends same-version suites in input order, returning a
directly executable suite. Duplicate case IDs, even with identical contents, and
combined size/case-limit violations fail closed. It never renames or drops cases.
This output includes original responses, so export only to an intended destination.

`inspect-suite SUITE --strict-exit` identifies repeated canonical responses and
conflicting expectations without exposing response content or hashes. Strict exit
is 1 for conflicting expectations. JSON booleans and numbers remain distinct.
Duplicates with identical assertions are informational, not a failing gate.

`inspect-policy POLICY` inventories rule kinds, exact paths, and declared ancestor
relationships without displaying constraint values. The library equivalent is
`inspect_policy`. Inspection supports up to 256 rules and a 1,000,000-byte
formatted report; exceeding a workflow bound fails closed with `INVALID_WORKFLOW`.

Package 0.3.0 adds authoring and regression tools around the existing schema 1.0
evaluator. All rules still participate. Input content never selects authority,
executes an action, or overrides another policy. Runtime dependencies remain
limited to Python's standard library.

## Author and debug

```text
constitutional-agent-testbench lint-policy examples/policy.json --strict-exit
constitutional-agent-testbench explain examples/policy.json examples/failing-response.json
constitutional-agent-testbench generate-probes examples/policy.json
```

Lint reports duplicate constraints, disjoint finite domains at identical paths,
and a finite ancestor domain with no candidate satisfying all declared descendants.
It does not rewrite rules or prove satisfiability when it finds no conflicts.
Explanations distinguish a missing object member from a non-object parent. They
include declared paths and rule identifiers, but no response or constraint values.

Probes start from a verified synthetic pass, then remove each rule's field and,
where applicable, substitute a verified disallowed value. Each probe records all
failed rules, so related-path collateral failures remain visible. The `suite`
member is directly accepted by `run-suite`; the entire probe bundle is not a suite.
Generated responses can contain declared policy values. They are synthetic
fixtures, not evidence of model behavior, independent rule isolation, or safety.

## Run regression fixtures and inspect gaps

Suite version `1.1` optionally adds `expected_rules` to each case, mapping rule IDs
to `{"passed": false, "reason_code": "FIELD_MISSING"}` assertions. Each assertion
requires both fields and a consistent public reason code. Omitted rules are not
asserted. `run-suite` reports `rule_assertion_mismatches` and fails the expectation
when an asserted rule disappears or its outcome/reason differs, even when the
overall expected failure still occurs. This also participates in strict exit and
migration expectation reports. Version 1.0 inputs and result shapes are unchanged.
An empty assertion map asserts only the overall verdict. Same-version curation
preserves assertions; changing suite versions is an explicit authoring decision.

```text
constitutional-agent-testbench run-suite examples/policy.json examples/regression-suite.json --strict-exit
constitutional-agent-testbench suite-coverage examples/policy.json examples/regression-suite.json --strict-exit
constitutional-agent-testbench compare-policies examples/policy.json examples/migration-policy.json examples/regression-suite.json
```

A suite is exactly `{"suite_version":"1.0","cases":[...]}`. Each case has exactly
`case_id`, `response`, and boolean `expected_passed`. Case identifiers must be
unique, start with an ASCII letter or digit, and contain only letters, digits,
periods, underscores, or hyphens (maximum 128 characters). Responses must be
objects. Expected failure is a successful regression assertion when the response
fails evaluation. Unknown fields, duplicate JSON members, and truthy numeric
expectations are rejected.

Coverage counts observed outcomes, even when a fixture expectation was wrong.
An unexercised outcome is a corpus gap, not evidence that the rule is unreachable.
Migration comparisons list added, removed, modified, and reordered rules plus
case verdict and rule-result changes. Both policies are evaluated independently.
A result on the supplied corpus does not establish general equivalence or decide
which policy should govern a real workflow.

## Create and verify a receipt

```text
constitutional-agent-testbench create-receipt examples/policy.json examples/passing-response.json > receipt.json
constitutional-agent-testbench verify-receipt examples/policy.json examples/passing-response.json receipt.json --strict-exit
```

The explicit shell redirection saves the receipt. Commands otherwise print JSON
and do not persist inputs. Verification recomputes policy and response digests
and every evaluation field, including rule order. Canonical JSON uses sorted
object keys, compact separators, UTF-8, and strict finite numbers; array order
and numeric representations remain significant. Policy digests include policy
identifiers and declared rule order. Whitespace and object member order do not
change digests.

Receipts contain no raw response, signature, timestamp, or identity assertion.
Anyone with inputs can create one. Verification proves consistency with the
supplied inputs and current evaluator, not authenticity or real-world safety.
Digests can still disclose equality or permit guessing of low-entropy inputs.

## Exit codes and boundaries

All successful computations default to exit 0, including valid negative results.
Controlled invalid input or exceeded limits return JSON on stderr and exit 2.
With `--strict-exit`, exit 1 means:

| Command | Condition |
| --- | --- |
| `lint-policy` | A conflict was found; duplicate-only findings do not fail. |
| `explain` | The response failed at least one rule. |
| `run-suite` | At least one expected pass state did not match. |
| `suite-coverage` | At least one rule lacks an observed pass or fail. |
| `compare-policies` | At least one fixture verdict or rule result changed. Definition-only changes may still exit 0. |
| `verify-receipt` | At least one digest or evaluation binding did not match. |

All JSON input arguments accept `-`, with at most one stdin input per invocation.
Existing playground and output-path exceptions remain unchanged. Inputs retain
the 1,000,000-byte, 32-level, and 100,000-node limits. Suites contain 1 to 256
cases and charge at most 32,000,000 canonical policy bytes across evaluations.
Lint charges at most 32,000,000 bytes of descendant comparison work. Targeted
probes support at most 64 rules, charge at most 32,000,000 policy bytes, and cap
formatted output at 1,000,000 bytes. Receipts have the same formatted output cap.
These limits can reject otherwise valid large workloads; splitting fixtures or
reducing synthetic domains is an explicit operator decision.

The library exposes the same functions through `constitutional_agent_testbench`.
Returned diagnostics, suite reports, comparisons, and receipts omit raw candidate
values. The unchanged Tk playground remains a single-response editor; these new
operator capabilities are available through the CLI and library.
