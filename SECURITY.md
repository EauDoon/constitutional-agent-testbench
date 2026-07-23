# Security

## Scope

This project performs deterministic, local evaluation of JSON data. It does not call models, initiate network requests, execute candidate content, or take external actions. Evaluation results omit candidate values.

## Safe operation

- Treat policies and responses as untrusted data, not executable instructions.
- Supply only files that the current operator is permitted to read.
- Review a policy before relying on its result.
- Keep JSON input files within the built-in 1,000,000-byte limit.
- Keep in-memory JSON values within 32 container levels and 100,000 nodes.
- Keep policies within 256 rules, 256 values per `one_of` rule, and 32 path segments.
- Keep personal data, credentials, access tokens, and confidential material out of policies, responses, examples, and issue reports.
- Write generated output only to an intended local destination.

The command line interface follows paths explicitly supplied by its operator. It does not search the file system. Standard file handling can follow a symbolic link supplied as an input or output path, so operators should verify path ownership in untrusted environments.

## Reporting a concern

Report a suspected vulnerability through GitHub's private vulnerability reporting for this repository. If that option is unavailable, open a minimal public issue requesting a private contact channel. Do not include private data, credentials, active exploit material, or affected-system identifiers in a public issue.

## Security boundary

A passing evaluation is a rule-conformance result only. It is not a security certification and does not establish that a response is safe, true, legal, complete, or aligned.

