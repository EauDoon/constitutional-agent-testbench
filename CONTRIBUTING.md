# Contributing

Contributions should preserve the project's narrow, deterministic scope.

## Requirements

- Use Python 3.11 or newer.
- Keep runtime code limited to the Python standard library.
- Do not add network access, model calls, action execution, telemetry, or persistent input storage.
- Do not add personal data, credentials, confidential identifiers, or realistic sensitive examples.
- Keep policy validation strict and fail closed on missing evaluation fields.
- Keep JSON output stable, sorted, and auditable.
- Add tests for every behavior change and reason code change.

## Development check

From the project root, expose `src` on `PYTHONPATH`, then run:

```text
python -m unittest discover -s tests -v
```

Also exercise `validate-policy`, `evaluate`, and `generate-synthetic` against the bundled examples.

## Change review

A proposed change should describe its public behavior, tests, compatibility impact, and any new limitation. Generated examples must remain fully synthetic. Changes to the policy schema or output contract require an explicit versioning decision.

By contributing, contributors agree that accepted changes are distributed under the MIT License.

