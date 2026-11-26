"""Refresh the offline architecture map using the installed evaluator and public fixtures."""

import argparse
import ast
import json
from html import escape
from pathlib import Path

from constitutional_agent_testbench import compare_policies, evaluate_suite, suite_coverage

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "architecture.html"
SOURCE = ROOT / "src" / "constitutional_agent_testbench"
EXAMPLES = ROOT / "examples" / "release-approval"
MODULES = {
    "common": ("Input boundaries", "Read bounded JSON and serialize stable output.", -220, 100, 30),
    "policy": ("Policy schema", "Validate the declared version, field paths and rule kinds.", -180, -70, -50),
    "evaluator": ("Rule evaluator", "Compile rules and produce a verdict and reason code for each rule.", 0, 0, 65),
    "suite": ("Fixture suite", "Check each fixture against its expected verdict and optional rule assertions.", 170, 90, -35),
    "coverage": ("Reason coverage", "Count observed outcomes and identify missing reason codes.", 210, -120, 20),
    "compare": ("Policy migration", "Compare individual rules and case verdicts across two policies.", 0, 155, -50),
    "precedence": ("Peer ordering", "Check whether changing the order of declared peers changes the evidence.", -35, -150, -70),
    "receipt": ("Receipt verification", "Bind the input digests to an evaluation and recompute the binding.", 255, 5, 90),
}


def snapshot():
    nodes = []
    for name, (label, summary, x, y, z) in MODULES.items():
        module = ast.parse((SOURCE / f"{name}.py").read_text("utf-8"))
        dependencies = sorted({item.module for item in module.body
                               if isinstance(item, ast.ImportFrom) and item.level == 1
                               and item.module in MODULES})
        nodes.append(dict(id=name, label=label, summary=summary, imports=dependencies,
                          position=[x, y, z]))

    def fixture(filename):
        return json.loads((EXAMPLES / filename).read_text("utf-8"))

    policy, candidate = fixture("policy-before.json"), fixture("policy-after.json")
    suite = fixture("suite-before.json")
    report = evaluate_suite(policy, suite)
    migration = compare_policies(policy, candidate, suite)
    covered = suite_coverage(policy, suite)
    return {"data": {"architecture": {"nodes": nodes}, "fixtureStudy": {
        "cases": report["cases"], "coverage": covered["rules"], "migration": migration["cases"]
    }}}


def render():
    result = snapshot()
    graph = result["data"]["architecture"]["nodes"]
    study = result["data"]["fixtureStudy"]
    parts = ['<details><summary>Module index and direct imports</summary><dl>']
    for node in graph:
        dependencies = ", ".join(node["imports"]) or "none in this map"
        parts.append(f'<dt>{escape(node["label"])} · <code>{node["id"]}.py</code></dt>'
                     f'<dd>{escape(node["summary"])} Imports {dependencies}.</dd>')
    parts.extend(['</dl></details>', '<details><summary>Fixture verdicts and rule changes</summary>',
                  '<table><thead><tr><th>Fixture</th><th>Before</th><th>After</th>'
                  '<th>Changed rules</th></tr></thead><tbody>'])
    for case in study["migration"]:
        verdicts = ["Pass" if case[key] else "Fail" for key in ("before_passed", "after_passed")]
        fields = [case["case_id"], *verdicts, ", ".join(case["changed_rule_results"]) or "None"]
        parts.append("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in fields) + "</tr>")
    parts.append('</tbody></table></details>')
    payload = json.dumps(result, indent=2, ensure_ascii=True).replace("<", r"\u003c")
    parts.append(f'<script id="study" type="application/json">{payload}</script>')
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the checked-in page is stale")
    args = parser.parse_args()
    page = PAGE.read_text("utf-8")
    start = "<!-- BEGIN generated evidence -->"
    end = "<!-- END generated evidence -->"
    before, current = page.split(start)
    _, after = current.split(end)
    refreshed = before + start + "\n" + render() + "\n" + end + after
    if args.check:
        if page != refreshed:
            parser.exit(1, "Architecture evidence is stale. Run scripts/refresh_architecture.py\n")
    else:
        PAGE.write_text(refreshed, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
