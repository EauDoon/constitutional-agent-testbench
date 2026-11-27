# Security

## Scope

The built-in evaluator performs deterministic, local evaluation of JSON data. It does not call models, initiate network requests, execute candidate content, or take external actions. Evaluation results omit candidate values.

The optional PrecedenceTrace library evaluator hook is different: it is a
Python callable supplied and executed by the embedding application. Treat that
hook as trusted code. This package does not sandbox it, impose a timeout, block
its network or filesystem access, or roll back its side effects.

## Authorization keys

`authorize` reads an Ed25519 private key from the file named by
`--private-key`. The key is never written to output or error messages. Keep
that file readable only by the authorizer process, and never give the agent
whose actions it approves access to it: the separation of the proposing agent
from the authorizer key is the whole guarantee. Signing uses the optional
`cryptography` package; no private-key arithmetic runs in pure Python.
Verification handles only public keys and uses a standard-library Ed25519
implementation that rejects non-canonical signature encodings and
out-of-range `S` values.

A verified decision proves which trusted key decided, about which exact
action, within which time window. It does not prove the policy was
sufficient. The key in `examples/rail/trusted-keys.json` is Consequence
Rail's published demo key, derived from a public label: never trust it
outside tests.

## Safe operation

- Treat policies and responses as untrusted data, not executable instructions.
- Supply only files that the current operator is permitted to read.
- Review a policy before relying on its result.
- Keep JSON input files, policies, and candidate responses within the built-in 1,000,000-byte limit.
- Keep in-memory JSON values within 32 container levels and 100,000 nodes.
- Keep policies within 256 rules, 256 values per `one_of` rule, and 32 path segments.
- Run PrecedenceTrace only on two to seven rules. The public mode refuses larger
  factorial workloads instead of sampling silently.
- Keep the declared policy and response small enough for the public
  100,000,000-byte estimated evaluation-work budget.
- Keep every in-memory policy, response, evaluator result, and final report
  within its separate 1,000,000-byte serialized PrecedenceTrace boundary. A
  report that exceeds its own cap fails closed with `ORDER_CHECK_TOO_LARGE`.
- Run untrusted or potentially blocking evaluator implementations in a
  separately constrained process; the library hook itself provides no
  execution isolation.
- Require every returned rule ID exactly once for complete coverage. Foreign,
  duplicate, kind/path-mismatched, and aggregate-incoherent results fail closed;
  stable incomplete failing results remain explicit nonconformance.
- Keep personal data, credentials, access tokens, and confidential material out of policies, responses, examples, and issue reports.
- Write generated output only to an intended local destination.

The command line interface uses paths explicitly supplied by its operator and
never searches the file system. Input paths and ancestor directories can follow
symbolic links. Atomic exports replace a symbolic link at the final destination
without reading or changing its target. This does not sandbox parent directories
or prevent another process from changing them. Verify input and destination
ownership before working in untrusted directories. Existing regular-file POSIX
permission bits are preserved except special bits; ownership and ACL preservation
are outside the export contract.

## Reporting a concern

Report a suspected vulnerability through GitHub's private vulnerability reporting for this repository. If that option is unavailable, open a minimal public issue requesting a private contact channel. Do not include private data, credentials, active exploit material, or affected-system identifiers in a public issue.

## Security boundary

A passing evaluation is a rule-conformance result only. It is not a security certification and does not establish that a response is safe, true, legal, complete, or aligned.

A clean PrecedenceTrace report is likewise bounded to one fixed input and the
tested evaluator. It does not prove commutativity, equal authority, policy
correctness, or absence of stateful behavior outside the observation contract.

