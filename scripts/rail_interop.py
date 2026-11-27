"""Run a signed Testbench decision through a live Consequence Rail sidecar.

Usage: python scripts/rail_interop.py RAIL_CHECKOUT

RAIL_CHECKOUT is a clone of github.com/EauDoon/consequence-rail. The script
starts its reference sidecar on a loopback port with
``--require-signed-authorization``, registers the example refund proposals,
signs decisions with the installed ``constitutional-agent-testbench
authorize`` command, and checks what the rail accepts and refuses:

- an allow decision for the proposal it was signed for is accepted;
- the same allow decision on a different proposal is refused;
- an unsigned approval is refused;
- a signed decision with one field changed is refused;
- a deny decision is accepted as a denial.

It needs Node.js 20 or later and the ``signing`` extra. The signing key is
the rail's public demonstration authorizer key, derived from a public label:
never trust it outside tests. Exit code 0 means every check matched.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAIL_EXAMPLES = ROOT / "examples" / "rail"
DEMO_AUTHORIZER_LABEL = b"consequence-rail/v0.1/authorization-decision-signing-key/not-a-secret"


def require(condition: bool, label: str) -> None:
    """Fail even under ``python -O``, which strips bare assert statements."""
    if not condition:
        raise AssertionError(f"Rail interop check failed: {label}")


def demo_authorizer_pem() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(DEMO_AUTHORIZER_LABEL).digest())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


class Rail:
    def __init__(self, checkout: Path) -> None:
        node = shutil.which("node")
        require(node is not None, "node is on PATH")
        self.process = subprocess.Popen(
            [str(node), str(checkout / "cmd" / "rail.js"), "--port", "0",
             "--require-signed-authorization"],
            cwd=checkout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        line = self.process.stdout.readline() if self.process.stdout else ""
        require("listening on http://127.0.0.1:" in line, "the sidecar started")
        self.base = line.strip().rsplit(" ", 1)[-1]
        # Loopback only: never route these requests through a proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(self, path: str, body: object) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Origin": self.base})
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()


def authorize(policy: Path, action: Path, key: Path, key_id: str, output: Path) -> dict:
    subprocess.run(
        [sys.executable, "-m", "constitutional_agent_testbench", "authorize", str(policy),
         str(action), "--private-key", str(key), "--key-id", key_id, "--output", str(output)],
        check=True, stdout=subprocess.DEVNULL)
    return json.loads(output.read_text(encoding="utf-8"))


def verify(decision: Path, action: Path, policy: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "constitutional_agent_testbench", "verify-authorization",
         str(decision), str(RAIL_EXAMPLES / "trusted-keys.json"), "--action", str(action),
         "--policy", str(policy)],
        check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    checkout = Path(argv[0]).resolve()
    policy = RAIL_EXAMPLES / "refund-policy.json"
    allowed = RAIL_EXAMPLES / "refund-proposal.json"
    over_limit = RAIL_EXAMPLES / "refund-proposal-over-limit.json"
    trusted = json.loads((RAIL_EXAMPLES / "trusted-keys.json").read_text(encoding="utf-8"))
    key_id = trusted["authorizer"][0]["key_id"]
    results = {}
    rail = Rail(checkout)
    try:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            key = work / "demo-authorizer.pem"
            key.write_bytes(demo_authorizer_pem())

            allow = authorize(policy, allowed, key, key_id, work / "allow.json")
            deny = authorize(policy, over_limit, key, key_id, work / "deny.json")
            require(allow["allow"] is True and deny["allow"] is False, "Testbench verdicts")
            for name, decision, action in (("allow", "allow.json", allowed),
                                           ("deny", "deny.json", over_limit)):
                report = verify(work / decision, action, policy)
                require(report["verified"] is True, f"Testbench verifies its own {name} decision")

            status, first = rail.post("/v0/actions", json.loads(allowed.read_text("utf-8")))
            require(status in (200, 201), "register the allowed proposal")
            require(first["action_digest"] == allow["action_digest"],
                    "the rail and the Testbench compute the same action digest")
            status, second = rail.post("/v0/actions", json.loads(over_limit.read_text("utf-8")))
            require(status in (200, 201), "register the over-limit proposal")

            def outcome(action_id: str, body: object) -> str:
                _, result = rail.post(f"/v0/actions/{action_id}/authorize", body)
                return result.get("state") or result.get("code") or "UNKNOWN"

            tampered = dict(deny)
            tampered["require_recovery_preflight"] = not deny["require_recovery_preflight"]
            unsigned = {"allow": True, "policy_id": allow["policy_id"],
                        "policy_digest": allow["policy_digest"]}
            checks = (
                ("allow decision on its own proposal", first["action_id"], allow, "AUTHORIZED"),
                ("allow decision reused on another proposal", second["action_id"], allow,
                 "AUTHORIZATION_ACTION_MISMATCH"),
                ("unsigned approval", second["action_id"], unsigned,
                 "AUTHORIZATION_SIGNATURE_REQUIRED"),
                ("signed decision with one field changed", second["action_id"], tampered,
                 "AUTHORIZATION_INVALID"),
                ("deny decision on its own proposal", second["action_id"], deny, "DENIED"),
            )
            for label, action_id, body, expected in checks:
                observed = outcome(action_id, body)
                results[label] = {"expected": expected, "observed": observed}
                require(observed == expected, f"{label}: expected {expected}, got {observed}")
    finally:
        rail.close()
    print(json.dumps({"rail_interop_passed": True, "checks": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
