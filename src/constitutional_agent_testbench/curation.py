"""Explicit corpus edits that preserve response content and assertion intent."""
from .suite import validate_suite, SuiteInputError
from .workflow import bounded_artifact, WorkflowInputError
from .policy import validate_policy
from .suite import evaluate_suite


def merge_suites(suite, incoming):
    """Append two owned suites; never silently rename, deduplicate or overwrite cases."""
    left, right = validate_suite(suite), validate_suite(incoming)
    if left["suite_version"] != right["suite_version"]:
        raise SuiteInputError("Merged suites must use the same version.")
    left["cases"].extend(right["cases"])
    return bounded_artifact(validate_suite(left))


def select_suite(suite, selection):
    """Select exact IDs in original corpus order, rejecting empty or misspelled selections."""
    fixtures = validate_suite(suite)
    bounded_artifact(selection)
    if (not isinstance(selection, list) or not 1 <= len(selection) <= 256
            or any(not isinstance(identifier, str) for identifier in selection)
            or len(set(selection)) != len(selection)):
        raise WorkflowInputError("Selection must contain 1 to 256 distinct case identifiers.")
    identifiers = set(selection)
    if identifiers - {case["case_id"] for case in fixtures["cases"]}:
        raise WorkflowInputError("Selection contains unknown case identifiers.")
    fixtures["cases"] = [case for case in fixtures["cases"] if case["case_id"] in identifiers]
    return bounded_artifact(fixtures)


def reduce_suite(policy, suite):
    """Greedily retain observed rule/reason coverage and every mismatching fixture."""
    current = validate_policy(policy)
    if len(current.rules) > 256:
        raise WorkflowInputError("Suite reduction supports at most 256 rules.")
    fixtures = validate_suite(suite)
    report = evaluate_suite(current, fixtures)
    signatures = []
    retained = set()
    for index, case in enumerate(report["cases"]):
        signature = {(row["rule_id"], row["passed"], row["reason_code"])
                     for row in case["evaluation"]["rule_results"]}
        # Keep observed verdict/expectation categories as well as rule evidence.
        signature.add(("verdict", case["evaluation"]["passed"], case["expected_passed"]))
        for identifier, assertion in fixtures["cases"][index].get("expected_rules", {}).items():
            signature.add(("assertion", identifier, assertion["passed"], assertion["reason_code"]))
        signatures.append(signature)
        if not case["matches_expectation"]:
            retained.add(index)
    uncovered = set().union(*signatures)
    for index in retained:
        uncovered -= signatures[index]
    while uncovered:
        chosen = max(range(len(signatures)), key=lambda index: len(signatures[index] & uncovered))
        retained.add(chosen)
        uncovered -= signatures[chosen]
    fixtures["cases"] = [case for index, case in enumerate(fixtures["cases"]) if index in retained]
    return bounded_artifact(validate_suite(fixtures))


def capture_assertions(policy, suite):
    """Fill rule assertions only after all existing expectations pass."""
    fixtures = validate_suite(suite)
    report = evaluate_suite(policy, fixtures)
    if not report["matches_expectations"]:
        raise WorkflowInputError("Assertion capture requires matching existing expectations.")
    fixtures["suite_version"] = "1.1"
    for case, observed in zip(fixtures["cases"], report["cases"], strict=True):
        case["expected_rules"] = {row["rule_id"]: {"passed": row["passed"], "reason_code": row["reason_code"]}
                                  for row in observed["evaluation"]["rule_results"]}
    return bounded_artifact(validate_suite(fixtures))


def shard_suite(suite, partition):
    """Select a zero-based round-robin shard in source order."""
    fixtures = validate_suite(suite)
    bounded_artifact(partition)
    if (not isinstance(partition, dict) or set(partition) != {"index", "count"}
            or type(partition["index"]) is not int or type(partition["count"]) is not int
            or not 1 <= partition["count"] <= len(fixtures["cases"])
            or not 0 <= partition["index"] < partition["count"]):
        raise WorkflowInputError("Partition requires integer index and count; each shard must be nonempty.")
    fixtures["cases"] = fixtures["cases"][partition["index"]::partition["count"]]
    return bounded_artifact(fixtures)
