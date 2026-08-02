"""Restricted, deterministic JSON rule evaluator shared by configuration engines."""

from collections.abc import Mapping
from typing import Any, cast


class InvalidRule(ValueError):
    """A stored rule uses syntax outside the restricted language."""


_OPERATORS = {
    "equals",
    "not_equals",
    "in",
    "not_in",
    "is_null",
    "is_not_null",
    "contains",
    "starts_with",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
}


def evaluate(rule: Any, values: Mapping[str, Any]) -> bool:
    if rule in (None, {}, []):
        return True
    if isinstance(rule, list):
        return all(evaluate(item, values) for item in rule)
    if not isinstance(rule, dict):
        raise InvalidRule("Rules must be JSON objects or arrays.")
    if set(rule) == {"all"} and isinstance(rule["all"], list):
        return all(evaluate(item, values) for item in rule["all"])
    if set(rule) == {"any"} and isinstance(rule["any"], list):
        return any(evaluate(item, values) for item in rule["any"])
    if not {"field", "operator"}.issubset(rule) or not set(rule) <= {
        "field",
        "operator",
        "value",
    }:
        raise InvalidRule("Rule leaf contains unsupported properties.")
    field, operator = rule["field"], rule["operator"]
    if not isinstance(field, str) or operator not in _OPERATORS:
        raise InvalidRule("Rule field or operator is unsupported.")
    if field not in values:
        raise InvalidRule("Rule field is not available to deterministic evaluation.")
    actual, expected = values.get(field), rule.get("value")
    if operator == "is_null":
        return actual is None
    if operator == "is_not_null":
        return actual is not None
    if operator == "equals":
        return actual == expected
    if operator == "not_equals":
        return actual != expected
    if operator == "in":
        return isinstance(expected, list) and actual in expected
    if operator == "not_in":
        return isinstance(expected, list) and actual not in expected
    if operator == "contains":
        return isinstance(actual, (str, list, tuple, set)) and expected in actual
    if operator == "starts_with":
        return isinstance(actual, str) and isinstance(expected, str) and actual.startswith(expected)
    try:
        if operator == "greater_than":
            return bool(cast("Any", actual) > cast("Any", expected))
        if operator == "greater_than_or_equal":
            return bool(cast("Any", actual) >= cast("Any", expected))
        if operator == "less_than":
            return bool(cast("Any", actual) < cast("Any", expected))
        return bool(cast("Any", actual) <= cast("Any", expected))
    except TypeError:
        return False
