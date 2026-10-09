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

Then run the checked-in eval scenarios, which record expected verdicts and
per-rule reason codes for `examples/policy.json`. Every case must name every rule
its policy declares, so a partially expected rule set fails the run:

```text
python -m evals.runner
```

Also exercise every public command against the bundled examples:

```text
python -m constitutional_agent_testbench --version
python -m constitutional_agent_testbench validate-policy examples/policy.json
python -m constitutional_agent_testbench evaluate examples/policy.json examples/passing-response.json
python -m constitutional_agent_testbench check-order examples/policy.json examples/passing-response.json
python -m constitutional_agent_testbench generate-synthetic examples/policy.json
```

Lint with the same pinned ruff release and rule set as CI. The rules are
declared in `pyproject.toml`:

```text
python -m pip install ruff==0.16.8
python -m ruff check --no-cache .
```

Type-check the public API the way a downstream consumer sees it. Install the
package first, so mypy reads the installed copy and its `py.typed` marker:

```text
python -m pip install --no-deps .
python -m pip install mypy==2.3.1
python -m mypy --python-version 3.11 --follow-imports=silent tests/static_typing/public_api.py
```

Measure branch coverage against the installed package. The settings live in
`pyproject.toml`, and `coverage report` fails below the 95 percent floor. Raise
the floor with tests; never lower it to make a change pass:

```text
python -m pip install --no-deps .
python -m pip install coverage==7.16.1
python -m coverage run -m unittest discover -s tests
python -m coverage report
```

Build and inspect both distribution formats before release:

```text
python -m build
python -m zipfile -l dist/*.whl
python -m tarfile -l dist/*.tar.gz
```

## Change review

A proposed change should describe its public behavior, tests, compatibility impact, and any new limitation. Generated examples must remain fully synthetic. Changes to the policy schema or output contract require an explicit versioning decision.

Every user-facing change adds a line under `## [Unreleased]` in
`CHANGELOG.md`, which follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Edit the version only in `src/constitutional_agent_testbench/_version.py`;
`pyproject.toml` reads it at build time and the package re-exports it as
`__version__`. `python scripts/check_version.py` confirms that the version, the
first `CHANGELOG.md` release heading, `release/vX.Y.Z-manifest.json` and the
README version line agree; CI runs it on every pull request.

By contributing, contributors agree that accepted changes are distributed under the Apache License 2.0.

