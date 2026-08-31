# Constitutional Agent Testbench v0.2.0 release assets

The v0.2.0 package metadata is recorded in
`release/v0.2.0-manifest.json`. The pinned release workflow builds a wheel and
source distribution, lists both archives, writes SHA-256 files, and retains the
assets for 14 days. It does not create or publish a remote release.

The strict-exit contract is backwards compatible: existing commands keep exit code zero for valid output unless `--strict-exit` is supplied. With the flag, conformance is zero, valid nonconformance or drift is one, and invalid or unresolved input is two.

The offline playground uses the same policy and evaluator semantics. Labeled
editors show a live pass/fail verdict plus the JSON result. It never writes
during evaluation. The Export result button opens an explicit save dialog and
is the only write path.
