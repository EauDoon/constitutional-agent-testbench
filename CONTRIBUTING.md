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
- For PrecedenceTrace changes, include foreign, duplicate, incomplete,
  nondeterministic, and byte/work-bound evaluator controls.

## Development check

From the project root, expose `src` on `PYTHONPATH`, then run:

```text
python -m unittest discover -s tests -v
```

Also exercise every public command against the bundled examples:

```text
python -m constitutional_agent_testbench.cli validate-policy examples/policy.json
python -m constitutional_agent_testbench.cli evaluate examples/policy.json examples/passing-response.json
python -m constitutional_agent_testbench.cli check-order examples/policy.json examples/passing-response.json
python -m constitutional_agent_testbench.cli generate-synthetic examples/policy.json
```

Build and inspect both distribution formats before release:

```text
python -m build
python -m zipfile -l dist/*.whl
python -m tarfile -l dist/*.tar.gz
```

## Change review

A proposed change should describe its public behavior, tests, compatibility impact, and any new limitation. Generated examples must remain fully synthetic. Changes to the policy schema or output contract require an explicit versioning decision.

Keep the version in `pyproject.toml`, `__version__` in the public package, and
the changelog entry synchronized.

By contributing, contributors agree that accepted changes are distributed under the MIT License.

