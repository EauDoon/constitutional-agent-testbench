# Decide, then act: the Testbench with Consequence Rail

The agent action stack splits one risky agent action into two jobs with two
owners:

- **Decide** (this package): evaluate the exact action against a policy and
  sign an allow or deny decision over the action's digest.
- **Act** ([Consequence Rail](https://github.com/EauDoon/consequence-rail)):
  refuse to run the action without a decision signed by a trusted authorizer,
  then reserve recourse, issue a single-use permit, execute and settle.

The agent that proposes an action never holds the authorizer key, so it cannot
approve its own action. This page walks one refund through both sides. Every
outcome below was observed against Consequence Rail `main` at `aec71b1` on
28 Nov 2026 (SGT), and `scripts/rail_interop.py` repeats the check in CI
against the rail's current `main`.

## 1. Write and test the policy

[`examples/rail/refund-policy.json`](../examples/rail/refund-policy.json) gates
the rail's demo refund: the right proposal schema and action type, enforced
assurance, an integer amount from 1 to 25,000 minor units, USD or SGD, and a
declared postcondition.

```bash
constitutional-agent-testbench validate-policy examples/rail/refund-policy.json
constitutional-agent-testbench lint-policy examples/rail/refund-policy.json --strict-exit
constitutional-agent-testbench generate-probes examples/rail/refund-policy.json
constitutional-agent-testbench evaluate examples/rail/refund-policy.json \
  examples/rail/refund-proposal.json --strict-exit
```

The policy reads the rail's `ActionProposal` as it is submitted. The rail adds
no defaults when it validates a proposal, so the JSON the Testbench evaluates
is the JSON whose digest the rail computes.

If the same rules also run in a runtime engine such as OPA or Cedar, replay
that engine's decision log through this policy with `compare-decision-log`
(see the README) to catch drift between the two.

## 2. Sign a decision

```bash
pip install "constitutional-agent-testbench[signing]"
constitutional-agent-testbench authorize examples/rail/refund-policy.json \
  examples/rail/refund-proposal.json \
  --private-key authorizer.pem --key-id demo-authorizer-ed25519-8RIF_vWD2A0pDZDH \
  --output allow.json
```

The output is an `AuthorizationDecision` v0.1. It binds:

| Field | Meaning |
| --- | --- |
| `action_digest` | SHA-256 of the proposal under the rail's canonical JSON, unpadded base64url. |
| `allow` | True only when every rule passed. A failing action still gets a signed deny. |
| `policy_id`, `policy_digest` | Which policy decided, and its exact content. |
| `evaluation_input_digest`, `evaluation_digest` | The JSON the Testbench evaluated and its full result, so a verifier can recompute the decision. |
| `decided_at`, `expires_at` | A validity window of at most one day; 300 seconds by default. |
| `signature` | Ed25519 by the authorizer key over all of the above. |

`authorizer.pem` above stands for your own unencrypted PKCS#8 Ed25519 key, and
its public half goes in the `authorizer` role of the rail's trusted-keys file.
The demo key ID belongs to the rail's public demonstration key, which is
derived from a public label; use it only in tests. A key held in an HSM or KMS
can sign through `authorization_signing_input` and `attach_signature` instead.

Anyone can check a decision without the private key:

```bash
constitutional-agent-testbench verify-authorization allow.json examples/rail/trusted-keys.json \
  --action examples/rail/refund-proposal.json --policy examples/rail/refund-policy.json --strict-exit
```

## 3. Submit it to the rail

```bash
node ./cmd/rail.js --port 0 --require-signed-authorization   # in the rail checkout
curl -s -X POST "$RAIL/v0/actions" -H 'content-type: application/json' -H "origin: $RAIL" \
  --data @examples/rail/refund-proposal.json                 # returns action_id and action_digest
curl -s -X POST "$RAIL/v0/actions/$ACTION_ID/authorize" -H 'content-type: application/json' \
  -H "origin: $RAIL" --data @allow.json
```

The `action_digest` the rail returns on registration equals the decision's
`action_digest`. What the rail does with each kind of decision:

| Submitted to `/authorize` | Rail result |
| --- | --- |
| The allow decision, on the proposal it was signed for | State `AUTHORIZED` |
| The same allow decision, on a different proposal | `AUTHORIZATION_ACTION_MISMATCH` |
| An unsigned `{allow, policy_id, policy_digest}` body | `AUTHORIZATION_SIGNATURE_REQUIRED` |
| A signed decision with one field changed after signing | `AUTHORIZATION_INVALID` |
| A signed deny for the over-limit proposal (amount 90,000) | State `DENIED` |

From `AUTHORIZED` the rail continues on its own: reserve recourse, issue a
permit, execute, verify the postcondition and export a settlement bundle. See
the rail's README for that half.

## 4. Run the whole check yourself

```bash
pip install ".[signing]"
git clone https://github.com/EauDoon/consequence-rail
python scripts/rail_interop.py consequence-rail
```

The script needs Node.js 20 or later. It starts the sidecar on a loopback
port, registers both example proposals, signs decisions with the installed
`authorize` command, verifies them with `verify-authorization`, submits all
five cases above and exits 1 if any rail result differs. The
`Rail interop` workflow runs it on pushes to `main`, on pull requests that
touch the signing path or the rail examples, and weekly.

## Limits

- The Testbench refuses to sign an action whose digest could not tell two
  evaluated inputs apart: a float such as `1.0` that the rail would digest as
  `1`, `-0.0`, integers beyond 2^53 - 1, or lone surrogates. Keep such values
  out of proposals it must approve.
- A decision proves which policy decided and what it saw. It does not prove
  the policy is right; that is what probes, suites and decision-log replay
  are for.
- The rail's reference sidecar is loopback only and not a production
  deployment boundary; see its threat model.
