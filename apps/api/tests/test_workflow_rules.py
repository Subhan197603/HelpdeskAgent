"""Unit tests for the non-executable workflow rule language."""

import pytest

from apps.api.app.core.rules import InvalidRule, evaluate


def test_empty_nested_and_comparison_rules_are_deterministic() -> None:
    values = {"priority": 3, "summary": "Fusion failure", "owner": None}
    assert evaluate([], values)
    assert evaluate(
        {
            "all": [
                {"field": "summary", "operator": "starts_with", "value": "Fusion"},
                {
                    "any": [
                        {"field": "priority", "operator": "greater_than", "value": 2},
                        {"field": "owner", "operator": "is_not_null"},
                    ]
                },
            ]
        },
        values,
    )
    assert not evaluate({"field": "priority", "operator": "in", "value": [1, 2]}, values)


@pytest.mark.parametrize(
    "rule",
    [
        "priority > 2",
        {"python": "True"},
        {"field": "priority", "operator": "sql", "value": "1=1"},
        {"all": "not-an-array"},
        {"field": "hidden", "operator": "is_null"},
    ],
)
def test_executable_or_unknown_rule_syntax_is_rejected(rule: object) -> None:
    with pytest.raises(InvalidRule):
        evaluate(rule, {"priority": 3})
