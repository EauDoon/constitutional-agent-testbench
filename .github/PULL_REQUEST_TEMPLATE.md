---
name: Pull request
about: Submit a change to Constitutional Agent Testbench
title: ""
labels: ''
assignees: ''
---

**Summary**

Describe the change in one or two sentences.

**Motivation and context**

Why is this change needed? What problem does it solve? Link any related issue.

**Change type**

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor
- [ ] Test change
- [ ] Other

**Scope check**

- [ ] Affects policy schema version 1.0
- [ ] Affects public EvaluationResult or RuleResult contracts
- [ ] Affects PrecedenceTrace mode
- [ ] Affects reason-code vocabulary
- [ ] None of the above

**Validation**

- [ ] `python -m constitutional_agent_testbench.cli validate-policy examples/policy.json` passes
- [ ] `python -m constitutional_agent_testbench.cli evaluate examples/policy.json examples/passing-response.json` returns `"passed": true`
- [ ] `python -m constitutional_agent_testbench.cli evaluate examples/policy.json examples/failing-response.json` returns `"passed": false`
- [ ] Added or updated tests where applicable

**Additional notes**

Anything else reviewers should know.
