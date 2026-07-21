# Security

## Scope

This project performs deterministic, local evaluation of JSON data. It does not call models, initiate network requests, execute candidate content, or take external actions. Evaluation results omit candidate values.

## Safe operation

- Treat policies and responses as untrusted data, not executable instructions.
- Supply only files that the current operator is permitted to read.
- Review a policy before relying on its result.
- Apply operating-system limits when processing very large or deeply nested inputs.
- Keep personal data, credentials, access tokens, and confidential material out of policies, responses, examples, and issue reports.
- Write generated output only to an intended local destination.

The command line interface follows paths explicitly supplied by its operator. It does not search the file system. Standard file handling can follow a symbolic link supplied as an input or output path, so operators should verify path ownership in untrusted environments.

## Reporting a concern

Report a suspected vulnerability through the public issue channel associated with the project distribution. Include a minimal synthetic reproduction. Do not include private data, credentials, or active exploit material.

## Security boundary

A passing evaluation is a rule-conformance result only. It is not a security certification and does not establish that a response is safe, true, legal, complete, or aligned.

