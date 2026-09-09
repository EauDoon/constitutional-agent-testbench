"""Explicit corpus edits that preserve response content and assertion intent."""
from .suite import validate_suite, SuiteInputError
from .workflow import bounded_artifact


def merge_suites(suite, incoming):
    """Append two owned suites; never silently rename, deduplicate or overwrite cases."""
    left, right = validate_suite(suite), validate_suite(incoming)
    if left["suite_version"] != right["suite_version"]:
        raise SuiteInputError("Merged suites must use the same version.")
    left["cases"].extend(right["cases"])
    return bounded_artifact(validate_suite(left))
