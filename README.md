# Constitutional Agent Testbench

**A deterministic contract checker for structured AI outputs.**

Constitutional Agent Testbench evaluates a JSON response against a declared, machine-readable policy. It gives builders a small and inspectable way to test whether structured output contains required fields, uses approved values, and preserves explicitly declared defaults before another workflow relies on it.

Its PrecedenceTrace mode also checks whether permuting declared peer rules
changes semantic results, reason evidence, or rule participation for one fixed
response.

The package is deliberately narrow. It does not call models, use a network, execute candidate content, take external actions, or persist inputs. Runtime code uses only the Python standard library. The result is a local evaluation layer that is easy to inspect, reproduce, and place beside a larger AI system.

![Workflow showing policy and JSON validation, rule evaluation, an optional peer-rule order check, and stable reporting.](https://raw.githubusercontent.com/EauDoon/constitutional-agent-testbench/main/.github/assets/project-overview.svg)

## Why it is useful

- Turn output expectations into versioned JSON rules instead of leaving them only in prompts or prose.
- Evaluate every declared rule and receive a clear pass state plus a stable reason code for each result.
- Fail closed when an expected path is absent.
- Generate verified passing and failing fixtures from the same policy.
- Keep evaluation local, dependency-free at runtime, and separate from model execution.

This is useful for development checks, regression suites, demonstrations, and pre-action validation of structured responses. It is not a safety certification and does not judge free-form reasoning.

## Core capabilities

| Capability | Behavior |
| --- | --- |
| Strict policy validation | Accepts version 1.0 policies with only declared fields and supported rule kinds. |
| Structured path evaluation | Resolves validated dot-separated paths through nested JSON objects. |
| Complete rule results | Evaluates every rule in policy order and reports a pass state and reason code for each one. |
| Fail-closed checks | Treats every missing evaluation path as a failed rule. |
| Stable JSON output | Emits sorted JSON object keys and stable public reason codes. |
| Synthetic fixture generation | Builds and re-evaluates one passing case and one failing case from a valid policy. |
| PrecedenceTrace | Exhaustively permutes two to seven peer rules and emits bounded order-drift evidence plus a reproducible swap-path witness. |
| Local operation | Makes no network or model calls and writes a file only when `--output` or the playground export action is explicitly supplied. |

## Quick start

Requirements:

- Python 3.11 or newer
- A source checkout of this repository

From the repository root, expose `src` on `PYTHONPATH`:

```bash
export PYTHONPATH=src
```

In PowerShell:

```powershell
$env:PYTHONPATH = "src"
```

After `python -m pip install --no-deps .`, the same operations are available as
the `constitutional-agent-testbench` console command.

Validate the bundled policy, then evaluate the passing example:

```text
python -m constitutional_agent_testbench.cli validate-policy examples/policy.json
python -m constitutional_agent_testbench.cli evaluate examples/policy.json examples/passing-response.json
```

The first command reports that the policy is valid. The second reports `"passed": true` and includes an ordered result for every rule. To inspect failure behavior, replace `passing-response.json` with `failing-response.json`.

## Command line interface

The command line interface supports five operations:

| Command | Purpose |
| --- | --- |
| `validate-policy` | Validate a policy and report its identifier and schema version. |
| `evaluate` | Evaluate a response and return the overall result plus every rule result. |
| `check-order` | Run PrecedenceTrace against one fixed response and two to seven declared peer rules. |
| `generate-synthetic` | Produce a verified passing and failing case, either on standard output or in an explicitly selected file. |
| `playground` | Open the offline policy playground, or run its headless smoke check. |

Run directly from a source checkout after adding `src` to `PYTHONPATH`:

```text
python -m constitutional_agent_testbench.cli validate-policy examples/policy.json
python -m constitutional_agent_testbench.cli evaluate examples/policy.json examples/passing-response.json
python -m constitutional_agent_testbench.cli check-order examples/policy.json examples/passing-response.json
python -m constitutional_agent_testbench.cli generate-synthetic examples/policy.json
python -m constitutional_agent_testbench.cli generate-synthetic examples/policy.json --output generated-cases.json
python -m constitutional_agent_testbench.cli playground --smoke-test
```

For `validate-policy`, `evaluate`, `check-order`, and `generate-synthetic`,
policy and response arguments accept `-` to read bounded strict JSON from
standard input. At most one argument may use standard input in a command, and
the same 1,000,000-byte limit and structural checks apply as for files. For
example:

```text
python -m constitutional_agent_testbench.cli evaluate examples/policy.json - < examples/passing-response.json
```

Operational results and controlled errors are JSON with sorted object keys. Help output remains plain command-line text. `--help` lists commands and argument conventions; unknown commands, unknown options, extra arguments, and missing arguments return `INVALID_COMMAND` with a usage hint and do not echo the supplied tokens. Policy validation errors name the failing rule when its identifier is valid, and the JSON error object then includes `policy_id`, `rule_id`, and `rule_index` for those known values. Invalid identifiers and input paths are still omitted.

When `--output` is supplied, `generate-synthetic` writes the complete case bundle and prints a path-free acknowledgement. `--output` writes a file and does not accept `-`. `playground` optional policy and response arguments are file paths and do not read `-` as standard input.

An important integration detail: completed `evaluate` and `check-order`
commands return process exit code `0` when their JSON result reports a failed
evaluation or order drift. Automation should inspect `passed`, `status`, and
`conforms_within_coverage`. Controlled command, input, policy, response,
generation, coverage-limit, and output errors return process exit code `2`
with a machine-readable error object on standard error.

Add `--strict-exit` to `evaluate` or `check-order` when automation should use
the process status as a gate. Conformance returns `0`, valid nonconformance or
drift returns `1`, and invalid or unresolved input returns `2`.

`playground` is offline and reuses the library evaluator. It writes nothing
during editing or evaluation. The **Export result** button opens an explicit
save dialog and is the only playground write path.

## Library use

The public API exposes policy validation, response evaluation, synthetic case
generation, and PrecedenceTrace order-conformance checking:

```python
from constitutional_agent_testbench import (
    check_order_conformance,
    evaluate_response,
    generate_synthetic_cases,
    validate_policy,
)

policy = validate_policy(
    {
        "schema_version": "1.0",
        "policy_id": "release-gate",
        "rules": [
            {
                "rule_id": "decision-approved",
                "kind": "equals",
                "path": "decision",
                "value": "approve",
            },
            {
                "rule_id": "blocked-is-false",
                "kind": "false",
                "path": "blocked",
            },
        ],
    }
)

result = evaluate_response(
    policy,
    {"decision": "approve", "blocked": False},
)
fixtures = generate_synthetic_cases(policy)
order_report = check_order_conformance(
    policy,
    {"decision": "approve", "blocked": False},
)
```

`result` contains:

- `policy_id`: the validated policy identifier;
- `passed`: `true` only when every rule passes; and
- `rule_results`: one ordered result per declared rule.

Each rule result contains `rule_id`, `kind`, `path`, `passed`, and `reason_code`. Candidate values are not copied into evaluation results. These fields are the public `EvaluationResult` and `RuleResult` contracts; the package includes a PEP 561 `py.typed` marker so type checkers can use them.

`evaluate_response` and `generate_synthetic_cases` accept a validated `Policy`
or a raw policy object and re-validate it. A non-object, oversized, or
structurally invalid response raises `EvaluationInputError`. Policy schema failures raise
`PolicyValidationError`, which names the failing rule when a valid `rule_id` is
already present and exposes `policy_id`, `rule_id`, and `rule_index` on the
exception. `generate_synthetic_cases` raises `SyntheticGenerationError` when a
verified passing and failing pair cannot be constructed. `check_order_conformance`
raises `PrecedenceTraceError` or `OrderCheckTooLargeError` when the check cannot
be performed within the public bounds.

`fixtures` contains:

- `policy_id`: the validated policy identifier;
- `passing_case`: a `response` plus its `evaluation` result, with `passed` true; and
- `failing_case`: a `response` plus its `evaluation` result, with `passed` false.

## PrecedenceTrace

PrecedenceTrace is a conformance mode, not a policy engine or precedence
resolver. For one fixed policy and response it:

1. exhaustively evaluates every permutation of two to seven rules;
2. evaluates each permutation three times and stops as
   `INCONCLUSIVE_NONDETERMINISTIC` if any repeated result differs;
3. compares semantic outcome, reason-code evidence keyed by stable rule ID,
   rule participation, and presentation order separately; and
4. returns a one-adjacent-swap witness when the drift is visible across one
   edge, or bounded endpoint evidence with an adjacent-swap path when a rule
   identity disappears between the differing regions.

Invoking the mode is the operator's declaration that the supplied rules should
be tested as peers. Policy schema 1.0 is unchanged and has no priority or
equal-authority field; undeclared fields still fail validation. The mode tests
behavior and does not infer institutional authority.

The optional library evaluator hook is trusted executable Python code, not
untrusted data. It must be deterministic, side-effect-free, locally bounded by
the caller, and emit the exact CAT result schema. PrecedenceTrace does not
sandbox it, interrupt it, or undo its effects. Additional fields, a mismatched
`policy_id`, foreign or duplicate rule IDs, kind/path mismatches, and a passing
result that omits a declared rule fail closed. The top-level pass state must
equal complete participation plus the conjunction of reported per-rule pass
states. A stable incomplete failing result is reported as non-conforming rather
than clean.

The result statuses are:

| Status | Meaning |
| --- | --- |
| `SEMANTIC_ORDER_DRIFT` | Overall pass changed under identical participation, or a pass state changed for the same rule identity wherever it was observed. |
| `EVIDENCE_ORDER_DRIFT` | Kind, path, or reason code changed for the same rule identity wherever it was observed. |
| `PARTICIPATION_ORDER_DRIFT` | The set or multiplicity of evaluated rule IDs changed without being counted again as outcome or evidence drift. |
| `COMPOUND_ORDER_DRIFT` | More than one independent semantic drift dimension changed within coverage. |
| `INCOMPLETE_RULE_COVERAGE` | At least one stable result omitted a declared rule. |
| `PRESENTATION_ONLY_DRIFT` | Only the ordered result array changed; this is non-semantic. |
| `NO_VARIANCE_OBSERVED` | No projected dimension changed within complete coverage. |
| `INCONCLUSIVE_NONDETERMINISTIC` | Repeated evaluation changed for at least one attempted order. |

The built-in evaluator returns rule results in the requested policy order, so
`PRESENTATION_ONLY_DRIFT` is the expected clean result for ordinary policies.
It still sets `conforms_within_coverage` to `true` because presentation order
is reported separately from semantic conformance.

The mode refuses eight or more rules rather than silently sampling and calling
the result exhaustive. It limits each in-memory policy, response, and evaluator
result to 1,000,000 serialized UTF-8 bytes, separately limits the final report
to 1,000,000 bytes, repeats every order three times, and applies a
100,000,000-byte deterministic work budget to planned inputs and observed
evaluator output. Reports expose unique orders, total evaluator calls,
input-work estimates, returned-result bytes, charged work, incomplete-order
counts, and the per-result and report limits. A valid evaluation can therefore
still fail closed with `ORDER_CHECK_TOO_LARGE` if its bounded witness report
would exceed the separate report limit. A custom evaluator can still consume unbounded time,
memory, network, or external resources before it returns; callers that do not
fully trust it must isolate it outside this process. A clean report is bounded
evidence for this input, policy, evaluator, and observation contract. It is not a mathematical proof of
commutativity, a proof that rules are institutionally equal, a correctness or
safety certification, or proof that any observed drift was caused by hidden
hierarchy. Short-circuiting, shared state, caching, time, and other evaluator
behavior can produce the same symptom.

## Policy format

A policy is a JSON object with exactly three top-level fields: `schema_version`, `policy_id`, and `rules`.

```json
{
  "policy_id": "example-policy",
  "rules": [
    {
      "kind": "required_field",
      "path": "summary",
      "rule_id": "summary-present"
    }
  ],
  "schema_version": "1.0"
}
```

The `rules` array must be non-empty. Policy and rule identifiers are 1 to 128 characters, start with a letter or digit, and may contain letters, digits, dots, underscores, or hyphens.

A path contains dot-separated object-key segments. Each segment starts with a letter or underscore and may continue with letters, digits, underscores, or hyphens. Paths traverse JSON objects only. Arrays may be evaluated as values but are not path containers.

### Supported rules

| Kind | Required rule fields | Pass condition |
| --- | --- | --- |
| `required_field` | `rule_id`, `kind`, `path` | The path exists, including when its value is null. |
| `equals` | `rule_id`, `kind`, `path`, `value` | The path value is JSON-equal to `value`. |
| `one_of` | `rule_id`, `kind`, `path`, `values` | The path value is JSON-equal to one listed value. |
| `false` | `rule_id`, `kind`, `path` | The path value is the JSON boolean false. |
| `empty_list` | `rule_id`, `kind`, `path` | The path value is an empty JSON array. |

Validation rejects:

- unsupported schema versions;
- missing or unknown policy and rule fields;
- unknown rule kinds;
- duplicate rule identifiers;
- empty or duplicate `one_of` values;
- duplicate JSON object members;
- non-finite numbers;
- malformed identifiers and paths; and
- values that JSON cannot represent.

## Evaluation results

The evaluator uses a small, stable reason-code vocabulary:

| Reason code | Meaning |
| --- | --- |
| `RULE_SATISFIED` | The rule passed. |
| `FIELD_MISSING` | The declared path was not present. |
| `VALUE_NOT_EQUAL` | An `equals` rule observed a different JSON value. |
| `VALUE_NOT_ALLOWED` | A `one_of` rule observed a value outside its allowed set. |
| `VALUE_NOT_FALSE` | A `false` rule did not observe the JSON boolean false. |
| `VALUE_NOT_EMPTY_LIST` | An `empty_list` rule did not observe an empty JSON array. |

All rules are evaluated even after one fails. This preserves a complete, inspectable record instead of returning only the first error.

## Deterministic behavior

Determinism comes from explicit constraints rather than hidden model behavior:

- Input files are decoded as UTF-8 JSON, with duplicate object members and non-finite numbers rejected.
- JSON equality uses a canonical, key-sorted representation. Python coercions do not apply, so the JSON boolean `true` is not equal to the JSON number `1`.
- Rules are evaluated in declared order, while emitted object keys are sorted.
- Evaluation adds no timestamps, randomness, external data, or model output.
- Nested policy values are copied during validation so later mutation of the source object cannot silently change the validated policy.
- Synthetic paths are processed in a stable order, and both generated cases are evaluated before they are returned.

Synthetic generation derives values from policy constraints and fixed neutral defaults. If constraints conflict, nested paths are incompatible, or a passing and failing pair cannot be verified, generation fails instead of labeling an invalid fixture as valid.

## Safety and limitations

A passing result proves only that the supplied JSON response conforms to the supplied supported rules. It does not prove that the response is safe, true, legal, complete, useful, or aligned with a model, organization, or policy outside this package.

Keep these boundaries in view:

- Policy quality and completeness remain the user's responsibility.
- Input authenticity and downstream consequences are outside the evaluator's scope.
- The built-in evaluator does not inspect prompts, free-form reasoning, model internals, or training data.
- The rule language does not provide array traversal, regular expressions, numeric ranges, arithmetic, or cross-field logic.
- JSON input files, validated policies, and candidate responses are limited to 1,000,000 bytes. In-memory JSON values are limited to 32 container levels and 100,000 nodes.
- PrecedenceTrace additionally limits each in-memory policy, response, and returned evaluator result to 1,000,000 serialized UTF-8 bytes.
- Policies are limited to 256 rules, `one_of` rules are limited to 256 candidate values, and field paths are limited to 32 segments.
- The command line interface follows explicitly supplied paths. Standard file handling may follow symbolic links.
- Generated output is written only when an operator supplies `--output`, and the operator is responsible for selecting an intended destination.
- Personal data, credentials, access tokens, and confidential material should be kept out of policies, responses, examples, and issue reports.

## Testing

From the repository root, expose `src` on `PYTHONPATH`, then run:

```text
python -m unittest discover -s tests -v
```

The test suite covers all supported rule kinds, strict policy validation,
missing-field failure, stable reason codes, JSON type distinctions, duplicate
object members, nested-value isolation, input limits, deterministic synthetic
generation, fail-closed handling of conflicting synthetic constraints,
PrecedenceTrace drift classes and planted counterexamples, and the command-line
JSON and exit-code contracts.

Continuous integration installs the package and runs the complete suite on Python 3.11 through 3.14. It also verifies the installed console command and builds and inspects both wheel and source-distribution artifacts.

Runtime imports are limited to the Python standard library and local package modules. The package declares no runtime dependencies.

## Repository map

| Path | Purpose |
| --- | --- |
| [`src/constitutional_agent_testbench/policy.py`](src/constitutional_agent_testbench/policy.py) | Policy schema, validation, and validated policy representation. |
| [`src/constitutional_agent_testbench/evaluator.py`](src/constitutional_agent_testbench/evaluator.py) | Rule evaluation and stable reason codes. |
| [`src/constitutional_agent_testbench/precedence.py`](src/constitutional_agent_testbench/precedence.py) | PrecedenceTrace enumeration, orthogonal projections and bounded swap-path witnesses. |
| [`src/constitutional_agent_testbench/synthetic.py`](src/constitutional_agent_testbench/synthetic.py) | Deterministic passing and failing fixture generation. |
| [`src/constitutional_agent_testbench/common.py`](src/constitutional_agent_testbench/common.py) | Strict JSON, canonical equality, path, and output helpers. |
| [`src/constitutional_agent_testbench/cli.py`](src/constitutional_agent_testbench/cli.py) | Command parsing, JSON results, error handling, and optional output writing. |
| [`src/constitutional_agent_testbench/playground.py`](src/constitutional_agent_testbench/playground.py) | Offline Tk playground with explicit export only. |
| [`tests/`](tests/) | Unit tests for validation, evaluation, synthetic generation, PrecedenceTrace, and the command-line contract. |
| [`examples/`](examples/) | A complete policy plus passing and failing response fixtures. |
| [`pyproject.toml`](pyproject.toml) | Python version, packaging metadata, and console entry points. |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history. |
| [`SECURITY.md`](SECURITY.md) | Safe-operation boundaries and vulnerability reporting guidance. |
| [`PROVENANCE.md`](PROVENANCE.md) | Public authorship and review record. |

## Authorship

EauDoon directs problem selection, product direction, requirements, evaluation,
rights review, and final acceptance. See [`PROVENANCE.md`](PROVENANCE.md) for
the complete statement.

## License

Released under the MIT License. See [`LICENSE`](LICENSE).
