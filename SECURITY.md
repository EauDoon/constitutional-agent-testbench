# Security

## Scope

The built-in evaluator performs deterministic, local evaluation of JSON data. It does not call models, initiate network requests, execute candidate content, or take external actions. Evaluation results omit candidate values.

The optional PrecedenceTrace library evaluator hook is different: it is a
Python callable supplied and executed by the embedding application. Treat that
hook as trusted code. This package does not sandbox it, impose a timeout, block
its network or filesystem access, or roll back its side effects.

## Safe operation

- Treat policies and responses as untrusted data, not executable instructions.
- Supply only files that the current operator is permitted to read.
- Review a policy before relying on its result.
- Keep JSON input files within the built-in 1,000,000-byte limit.
- Supply Unicode scalar text; unpaired surrogates are rejected because they
  cannot be represented in strict UTF-8 output.
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

The command line interface follows paths explicitly supplied by its operator. It does not search the file system. Standard file handling can follow a symbolic link supplied as an input or output path, so operators should verify path ownership in untrusted environments.

## Reporting a concern

Report a suspected vulnerability through GitHub's private vulnerability reporting for this repository. If that option is unavailable, open a minimal public issue requesting a private contact channel. Do not include private data, credentials, active exploit material, or affected-system identifiers in a public issue.

## Security boundary

A passing evaluation is a rule-conformance result only. It is not a security certification and does not establish that a response is safe, true, legal, complete, or aligned.

A clean PrecedenceTrace report is likewise bounded to one fixed input and the
tested evaluator. It does not prove commutativity, equal authority, policy
correctness, or absence of stateful behavior outside the observation contract.
