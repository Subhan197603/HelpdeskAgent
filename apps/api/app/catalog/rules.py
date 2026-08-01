"""Validation for the restricted, data-only conditional-field rule language."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = str | int | float | bool | None


class ConditionPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,99}$")]
    operator: Literal[
        "equals",
        "not_equals",
        "in",
        "not_in",
        "is_empty",
        "is_not_empty",
    ]
    value: Scalar | list[Scalar] = None

    @model_validator(mode="after")
    def validate_operator_value(self) -> "ConditionPredicate":
        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not self.value or len(self.value) > 100:
                raise ValueError("Set operators require a bounded non-empty value list")
        elif self.operator in {"is_empty", "is_not_empty"}:
            if self.value is not None:
                raise ValueError("Empty-state operators do not accept a value")
        elif isinstance(self.value, list):
            raise ValueError("Comparison operators require a scalar value")
        return self


class ConditionalRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    all: Annotated[list[ConditionPredicate] | None, Field(max_length=20)] = None
    any: Annotated[list[ConditionPredicate] | None, Field(max_length=20)] = None

    @model_validator(mode="after")
    def validate_single_group(self) -> "ConditionalRule":
        populated = [group for group in (self.all, self.any) if group is not None]
        if len(populated) != 1 or not populated[0]:
            raise ValueError("A conditional rule requires exactly one non-empty all/any group")
        return self


def parse_conditional_rule(value: object) -> ConditionalRule | None:
    if value in ({}, None):
        return None
    return ConditionalRule.model_validate(value)
