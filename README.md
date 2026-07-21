# Constitutional Agent Testbench

Constitutional Agent Testbench is a small, deterministic Python package for checking structured candidate responses against declared JSON rules. It is designed for local testing, reproducible examples, and inspectable evaluation records.

The package does not call models, take external actions, use a network, retain inputs, or depend on private schemas. Its runtime uses only the Python standard library. It writes a local file only when an operator explicitly supplies the `--output` option.

## What it does

- Strictly validates version 1.0 policies.
- Resolves dot-separated paths through JSON objects.
- Evaluates every rule and emits stable reason codes.
- Fails closed when a required evaluation path is missing.
- Produces sorted, stable JSON output.
- Generates deterministic synthetic passing and failing cases.

## Important limitation

Conformance to declared machine-readable rules is not proof of safety, truth, legality, or model alignment. A result only shows whether the supplied JSON response conforms to the supplied supported rules. Policy quality, policy completeness, input authenticity, and consequences outside this evaluator remain the responsibility of the user.

## Policy format

A policy is a JSON object with exactly three top-level fields:

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

Policy identifiers and rule identifiers contain letters, digits, dots, underscores, or hyphens. A field path contains dot-separated object-key segments. Each segment starts with a letter or underscore and may continue with letters, digits, underscores, or hyphens. Arrays are values, not path containers.

Supported rule kinds:

| Kind | Required rule fields | Pass condition |
| --- | --- | --- |
| `required_field` | `rule_id`, `kind`, `path` | The path exists, including when its value is null. |
| `equals` | `rule_id`, `kind`, `path`, `value` | The path value is JSON-equal to `value`. |
| `one_of` | `rule_id`, `kind`, `path`, `values` | The path value is JSON-equal to one listed value. |
| `false` | `rule_id`, `kind`, `path` | The path value is the JSON boolean false. |
| `empty_list` | `rule_id`, `kind`, `path` | The path value is an empty JSON array. |

Unknown fields, unknown rule kinds, duplicate rule identifiers, empty `one_of` lists, duplicate `one_of` values, duplicate JSON object members, non-finite numbers, and malformed paths are rejected.

## Command line use

Run directly from a source checkout by adding `src` to `PYTHONPATH` using the normal mechanism for your shell.

```text
python -m constitutional_agent_testbench.cli validate-policy examples/policy.json
python -m constitutional_agent_testbench.cli evaluate examples/policy.json examples/passing-response.json
python -m constitutional_agent_testbench.cli generate-synthetic examples/policy.json
python -m constitutional_agent_testbench.cli generate-synthetic examples/policy.json --output generated-cases.json
```

Operational command results and controlled errors are JSON with sorted keys. Help output remains plain command-line text. `generate-synthetic` writes the full case bundle when `--output` is supplied and prints a path-free acknowledgement.

## Library use

```python
from constitutional_agent_testbench import evaluate_response, validate_policy

policy = validate_policy(
    {
        "schema_version": "1.0",
        "policy_id": "example-policy",
        "rules": [
            {
                "rule_id": "ready-is-false",
                "kind": "false",
                "path": "ready",
            }
        ],
    }
)
result = evaluate_response(policy, {"ready": False})
```

The returned result contains `policy_id`, `passed`, and an ordered `rule_results` list. Each rule result contains the rule identifier, kind, path, pass state, and reason code. Candidate values are not copied into evaluation results.

## Synthetic cases

Synthetic generation derives values only from the policy and fixed neutral defaults. It does not use real personal data. If the policy has conflicting constraints and no passing response can be constructed, generation fails instead of labeling an invalid case as passing.

## Testing

```text
python -m unittest discover -s tests -v
```

## Authorship

Project direction and requirements are by Oonyl. This public package was drafted and tested with OpenAI Codex. Final evaluation, review, and acceptance remain with Oonyl. See `PROVENANCE.md` for the complete statement.

This is an independent community project. It is not an OpenAI product, and OpenAI does not endorse it.
