"""Public API for Constitutional Agent Testbench."""

from .evaluator import (
    EvaluationInputError,
    EvaluationResult,
    RuleResult,
    evaluate_response,
)
from .policy import Policy, PolicyValidationError, Rule, validate_policy
from .precedence import (
    OrderCheckTooLargeError,
    PrecedenceTraceError,
    check_order_conformance,
)
from .synthetic import SyntheticGenerationError, generate_synthetic_cases

__all__ = [
    "EvaluationInputError",
    "EvaluationResult",
    "OrderCheckTooLargeError",
    "Policy",
    "PolicyValidationError",
    "PrecedenceTraceError",
    "Rule",
    "RuleResult",
    "SyntheticGenerationError",
    "evaluate_response",
    "check_order_conformance",
    "generate_synthetic_cases",
    "validate_policy",
]

__version__ = "0.2.0"

