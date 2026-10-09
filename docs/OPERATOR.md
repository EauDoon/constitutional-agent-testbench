# Local policy operator workflow

See the [corpus guide](CORPUS.md) for a complete executable curation,
assertion, receipt, replay, and atomic-export workflow.

## Command catalog

Use the installed `constitutional-agent-testbench` command after
`python -m pip install --no-deps .`. For source-only development, set
`PYTHONPATH=src` and use `python -m constitutional_agent_testbench.cli` instead.

| Command | Purpose |
| --- | --- |
| `validate-policy` | Validate a policy and report its identifier and schema version. |
| `evaluate` | Evaluate a response and return the overall result plus every rule result. |
| `check-order` | Run PrecedenceTrace against one fixed response and two to seven declared peer rules. |
| `generate-synthetic` | Produce a verified passing and failing case, either on standard output or in an explicitly selected file. |
| `playground` | Open the offline policy playground, or run its headless smoke check. |
| `lint-policy` | Identify exact-path conflicts, incompatible descendants, and duplicate constraints. |
| `explain` | Show absent members and non-object parents without copying candidate values. |
| `generate-probes` | Produce verified per-rule mutations and an executable fixture suite. |
| `run-suite` | Compare every fixture result with its explicit expected pass state. |
| `suite-coverage` | Count observed pass/fail outcomes and reason codes for each rule. |
| `compare-policies` | Show definition changes and fixture impact between two independently evaluated policies. |
| `create-receipt` | Bind policy and response digests to their deterministic evaluation. |
| `verify-receipt` | Recompute and compare the complete receipt against supplied inputs. |
| `inspect-policy` / `inspect-suite` | Inventory paths or detect duplicate inputs and conflicting assertions without values. |
| `merge-suites` / `select-suite` | Combine corpora safely or select exact case IDs. |
| `triage-suite` / `reduce-suite` | Diagnose regressions or retain a deterministic subset preserving observed evidence. |
| `create-suite-receipt` / `verify-suite-receipt` | Bind and recompute whole-corpus evidence. |
| `validate-suite` / `import-responses` | Validate fixture syntax or import response arrays with explicit verdict expectations. |
| `capture-assertions` / `audit-assertions` | Capture matching observed rule results or audit assertion intent against a policy. |
| `diff-suites` / `deduplicate-suite` | Review corpus edits without values or retain the first exact fixture duplicate. |
| `shard-suite` / `select-outcomes` | Split executable suites or select observed verdict and regression cohorts. |
| `migration-expectations` / `check-suite` | Gate expectation regressions or combine policy and fixture preflight checks. |
| `create-replay` / `replay` | Create and independently check portable JSON replay bundles. |

Operational results and controlled errors are JSON with sorted object keys;
help remains plain text. Unknown commands or options and missing or extra
arguments return `INVALID_COMMAND` with a usage hint without echoing tokens.

For `validate-policy`, `evaluate`, `check-order`, and `generate-synthetic`, policy
and response arguments accept `-` for bounded strict JSON on standard input.
At most one input argument may use standard input. The same 1,000,000-byte and
structural limits apply to files and standard input. `--output` selects a file
and does not accept `-`; playground inputs are file paths only.

Inputs must be UTF-8 without a byte order mark. On Windows, PowerShell 5.1
`Out-File` and the `>` redirection write UTF-16 with a byte order mark, which is
rejected as `INVALID_JSON_INPUT` with a message naming the encoding. Use
PowerShell 7 `Set-Content -Encoding utf8NoBOM`, or let the command write its
result with `--output`.

For `evaluate` and `check-order`, a completed nonconformance result returns `0`
unless `--strict-exit` is supplied. With it, conformance returns `0`, valid
nonconformance or drift returns `1`, and invalid or unresolved input returns `2`.
Other commands have the command-specific gates described below. Inspect the JSON
result as well as the exit status.

## Corpus inspection and curation

`reduce-suite POLICY SUITE` returns an executable subset, retaining every observed
rule/pass/reason combination, verdict/expectation category, and every mismatching
fixture. A greedy algorithm breaks ties by original order; final cases retain
source order. It supports up to 256 rules. It is deterministic, not a globally
minimal suite or a guarantee about unobserved inputs. Responses are included.

`triage-suite POLICY SUITE --strict-exit` reports only cases whose explicit
expectations failed, groups their actual failures by rule/path/reason, and retains
unexpected passes and rule-assertion mismatches. It omits response values. Strict
exit follows regression expectations, not whether all responses passed policy.

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

Authoring and regression tools use the schema 1.0
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

`create-replay POLICY SUITE` produces one self-contained JSON bundle with policy,
fixtures and their receipt. **Bundles contain original policy and response values.**
`replay BUNDLE --strict-exit` recomputes evidence using the installed evaluator.
Exit 0 requires both valid bindings and matching fixture expectations; exit 1
means a valid inconsistency or regression, and malformed artifacts return 2.
When bindings fail, `matches_expectations` is null rather than a trusted claim.
Replay never loads a module, follows a path, calls a model, or executes a command
from bundle contents. All fields are strict, versioned data. Combined bundles
must fit the existing JSON nesting/node and 1,000,000-byte formatted limits.

`create-suite-receipt POLICY SUITE` and `verify-suite-receipt POLICY SUITE RECEIPT
--strict-exit` extend receipt consistency checking to entire corpora. They bind
case order, responses, expected verdicts, optional rule assertions, and all actual
rule results. Receipts omit raw responses. Verification independently recomputes
the complete report; changing a boolean to a number fails consistency checking.
These are separate versioned artifacts, preserving existing single-response
receipts. Anyone with the inputs can recreate them; they are not signatures.

```text
constitutional-agent-testbench create-receipt examples/policy.json examples/passing-response.json > receipt.json
constitutional-agent-testbench verify-receipt examples/policy.json examples/passing-response.json receipt.json --strict-exit
```

The explicit shell redirection saves the receipt. Commands otherwise print JSON
and do not persist inputs. Verification recomputes policy and response digests
and every evaluation field, including rule order. Canonical JSON uses sorted
object keys, compact separators, UTF-8, and strict finite numbers; array order
and numeric representations remain significant. The same canonical form decides
`equals` and `one_of` evaluation, not only digests: an integer literal such as
`1` never equals `1.0` or `1e0`, and `0.0` never equals `-0.0`. Policy digests include policy
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
