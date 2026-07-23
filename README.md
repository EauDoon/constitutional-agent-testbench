# Constitutional Agent Testbench

**A deterministic contract checker for structured AI outputs.**

Constitutional Agent Testbench evaluates a JSON response against a declared, machine-readable policy. It gives builders a small and inspectable way to test whether structured output contains required fields, uses approved values, and preserves explicitly declared defaults before another workflow relies on it.

The package is deliberately narrow. It does not call models, use a network, execute candidate content, take external actions, or persist inputs. Runtime code uses only the Python standard library. The result is a local evaluation layer that is easy to inspect, reproduce, and place beside a larger AI system.

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
| Local operation | Makes no network or model calls and writes a file only when `--output` is explicitly supplied. |

## Quick start

Requirements:

- Python 3.11 or newer
- A source checkout of this repository

From the repository root, expose `src` on `PYTHONPATH`. In PowerShell:

```powershell
$env:PYTHONPATH = "src"
```

Validate the bundled policy, then evaluate the passing example:

```text
python -m constitutional_agent_testbench.cli validate-policy examples/policy.json
python -m constitutional_agent_testbench.cli evaluate examples/policy.json examples/passing-response.json
```

The first command reports that the policy is valid. The second reports `"passed": true` and includes an ordered result for every rule. To inspect failure behavior, replace `passing-response.json` with `failing-response.json`.

## Command line interface

The command line interface supports three operations:

| Command | Purpose |
| --- | --- |
| `validate-policy` | Validate a policy and report its identifier and schema version. |
| `evaluate` | Evaluate a response and return the overall result plus every rule result. |
| `generate-synthetic` | Produce a verified passing and failing case, either on standard output or in an explicitly selected file. |

Run directly from a source checkout after adding `src` to `PYTHONPATH`:

```text
python -m constitutional_agent_testbench.cli validate-policy examples/policy.json
python -m constitutional_agent_testbench.cli evaluate examples/policy.json examples/passing-response.json
python -m constitutional_agent_testbench.cli generate-synthetic examples/policy.json
python -m constitutional_agent_testbench.cli generate-synthetic examples/policy.json --output generated-cases.json
```

Operational results and controlled errors are JSON with sorted object keys. Help output remains plain command-line text. When `--output` is supplied, `generate-synthetic` writes the complete case bundle and prints a path-free acknowledgement.

An important integration detail: a completed `evaluate` command returns process exit code `0` even when the JSON result contains `"passed": false`. Automation should inspect the `passed` field. Controlled command, input, policy, response, generation, and output errors return process exit code `2` with a machine-readable error object on standard error.

## Library use

The public API exposes policy validation, response evaluation, and synthetic case generation:

```python
from constitutional_agent_testbench import (
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
```

`result` contains:

- `policy_id`: the validated policy identifier;
- `passed`: `true` only when every rule passes; and
- `rule_results`: one ordered result per declared rule.

Each rule result contains `rule_id`, `kind`, `path`, `passed`, and `reason_code`. Candidate values are not copied into evaluation results.

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
- The package does not inspect prompts, free-form reasoning, model internals, or training data.
- The rule language does not provide array traversal, regular expressions, numeric ranges, arithmetic, or cross-field logic.
- JSON input files are limited to 1,000,000 bytes. In-memory JSON values are limited to 32 container levels and 100,000 nodes.
- Policies are limited to 256 rules, `one_of` rules are limited to 256 candidate values, and field paths are limited to 32 segments.
- The command line interface follows explicitly supplied paths. Standard file handling may follow symbolic links.
- Generated output is written only when an operator supplies `--output`, and the operator is responsible for selecting an intended destination.
- Personal data, credentials, access tokens, and confidential material should be kept out of policies, responses, examples, and issue reports.

## Testing

From the repository root, expose `src` on `PYTHONPATH`, then run:

```text
python -m unittest discover -s tests -v
```

The test suite covers all supported rule kinds, strict policy validation, missing-field failure, stable reason codes, JSON type distinctions, duplicate object members, nested-value isolation, input limits, deterministic synthetic generation, fail-closed handling of conflicting synthetic constraints, and the command-line JSON and exit-code contracts.

Continuous integration installs the package and runs the complete suite on Python 3.11 through 3.14. It also verifies the installed console command against the bundled synthetic policy.

Runtime imports are limited to the Python standard library and local package modules. The package declares no runtime dependencies.

## Repository map

| Path | Purpose |
| --- | --- |
| [`src/constitutional_agent_testbench/policy.py`](src/constitutional_agent_testbench/policy.py) | Policy schema, validation, and validated policy representation. |
| [`src/constitutional_agent_testbench/evaluator.py`](src/constitutional_agent_testbench/evaluator.py) | Rule evaluation and stable reason codes. |
| [`src/constitutional_agent_testbench/synthetic.py`](src/constitutional_agent_testbench/synthetic.py) | Deterministic passing and failing fixture generation. |
| [`src/constitutional_agent_testbench/common.py`](src/constitutional_agent_testbench/common.py) | Strict JSON, canonical equality, path, and output helpers. |
| [`src/constitutional_agent_testbench/cli.py`](src/constitutional_agent_testbench/cli.py) | Command parsing, JSON results, error handling, and optional output writing. |
| [`tests/`](tests/) | Unit tests for validation, evaluation, and synthetic generation. |
| [`examples/`](examples/) | A complete policy plus passing and failing response fixtures. |
| [`pyproject.toml`](pyproject.toml) | Python version, packaging metadata, and console entry point. |
| [`SECURITY.md`](SECURITY.md) | Safe-operation boundaries and vulnerability reporting guidance. |
| [`PROVENANCE.md`](PROVENANCE.md) | Public authorship and review record. |

## Authorship and independence

OpenAI Codex assisted with drafting and testing. Oonyl directed, reviewed, and takes responsibility for the result. See [`PROVENANCE.md`](PROVENANCE.md) for the complete statement.

This is an independent community project. It is not an OpenAI product, and OpenAI does not endorse it.

## License

Released under the MIT License. See [`LICENSE`](LICENSE).
