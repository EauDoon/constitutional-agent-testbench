# Constitutional Agent Testbench v0.5.4 release assets

The v0.5.4 package metadata is recorded in
`release/v0.5.4-manifest.json`. The pinned release workflow builds a wheel and
source distribution, lists both archives, writes SHA-256 files, and retains the
assets for 14 days. It does not create or publish a remote release.

Unknown options are reported as unknown options even when a required path is
also missing. A recognized flag without its paths is still a missing argument.

The exhaustive and `INCONCLUSIVE_NONDETERMINISTIC` PrecedenceTrace reports share one
`coverage` contract, so a consumer can read the same fields from either. Values that
cannot be known after an early stop, such as incomplete-order counts, are reported as
`null` alongside the unresolved `conforms_within_coverage`.

The distribution installs two console commands, `constitutional-agent-testbench`
and `constitutional-agent-testbench-playground`. A third entry point that pointed
at the repository-only `evals` package was removed in 0.5.2 because the package is
outside `src/` and ships in neither archive; the evaluation runner stays available
inside a checkout as `python -m evals.runner`.

The strict-exit contract is backwards compatible: existing commands keep exit code zero for valid output unless `--strict-exit` is supplied. With the flag, conformance is zero, valid nonconformance or drift is one, and invalid or unresolved input is two.

The offline playground uses the same policy and evaluator semantics. Labeled
editors show a live pass/fail verdict plus the JSON result. It never writes
during evaluation. The Export result button opens an explicit save dialog and
is the only write path.
