"""Explicit corpus edits that preserve response content and assertion intent."""
from .suite import validate_suite, SuiteInputError
from .workflow import bounded_artifact, WorkflowInputError


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
