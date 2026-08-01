"""Authoritative validation and normalization for immutable request forms."""

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from apps.api.app.catalog.models import FormFieldRecord
from apps.api.app.catalog.rules import ConditionPredicate, parse_conditional_rule
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.tickets.schemas import CustomFieldInput


def validate_and_normalize(
    records: list[FormFieldRecord],
    supplied: list[CustomFieldInput],
    *,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Validate values against one immutable form version and return JSON-safe values."""
    errors: dict[str, list[str]] = {}
    raw: dict[str, Any] = {}
    for item in supplied:
        if item.field_code in raw:
            errors.setdefault(f"custom_fields.{item.field_code}", []).append(
                "Field must be supplied only once."
            )
        else:
            raw[item.field_code] = item.value

    grouped: dict[str, list[FormFieldRecord]] = {}
    for record in records:
        grouped.setdefault(record.field_code, []).append(record)
    for code in raw.keys() - grouped.keys():
        errors.setdefault(f"custom_fields.{code}", []).append("Unknown field.")

    normalized: dict[str, Any] = {}
    for code, field_records in grouped.items():
        field = field_records[0]
        active = _condition_applies(field.condition, raw)
        value = raw.get(code)
        if not active:
            if code in raw and value not in (None, "", []):
                errors.setdefault(f"custom_fields.{code}", []).append(
                    "Field is not applicable for the supplied values."
                )
            continue
        if value in (None, "", []):
            if field.required and require_complete:
                errors.setdefault(f"custom_fields.{code}", []).append("Field is required.")
            normalized[code] = None
            continue
        try:
            result = _normalize(field, field_records, value)
        except ValueError as exc:
            errors.setdefault(f"custom_fields.{code}", []).append(str(exc))
            continue
        _validate_bounds(field, result, errors)
        normalized[code] = result

    if errors:
        raise ValidationError("The draft does not match its request form.", field_errors=errors)
    return normalized


def _condition_applies(condition: object, values: dict[str, Any]) -> bool:
    rule = parse_conditional_rule(condition)
    if rule is None:
        return True
    predicates = rule.all if rule.all is not None else rule.any
    assert predicates is not None
    results = [
        _predicate_matches(predicate, values.get(predicate.field)) for predicate in predicates
    ]
    return all(results) if rule.all is not None else any(results)


def _predicate_matches(predicate: ConditionPredicate, actual: Any) -> bool:
    if predicate.operator == "is_empty":
        return actual in (None, "", [])
    if predicate.operator == "is_not_empty":
        return actual not in (None, "", [])
    if predicate.operator == "equals":
        return bool(actual == predicate.value)
    if predicate.operator == "not_equals":
        return bool(actual != predicate.value)
    expected = predicate.value
    assert isinstance(expected, list)
    return (actual in expected) == (predicate.operator == "in")


def _normalize(field: FormFieldRecord, records: list[FormFieldRecord], value: Any) -> Any:
    data_type = field.data_type
    if data_type in {"TEXT", "LONG_TEXT"}:
        if not isinstance(value, str):
            raise ValueError("Value must be text.")
        return " ".join(value.split()) if data_type == "TEXT" else value.strip()
    if data_type == "NUMBER":
        if isinstance(value, bool):
            raise ValueError("Value must be a number.")
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError("Value must be a number.") from None
        if not decimal_value.is_finite():
            raise ValueError("Value must be a finite number.")
        return str(decimal_value.normalize())
    if data_type == "BOOLEAN":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ValueError("Value must be a boolean.")
    if data_type == "DATE":
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise ValueError("Value must be an ISO 8601 date.") from None
    if data_type == "TIMESTAMP":
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Value must be an ISO 8601 datetime.") from None
        if parsed.tzinfo is None:
            raise ValueError("Datetime must include a timezone.")
        return parsed.isoformat()
    if data_type in {"USER", "GROUP", "SERVICE", "MODULE", "ASSET"}:
        try:
            return str(UUID(str(value)))
        except ValueError:
            raise ValueError("Value must be a UUID reference.") from None
    options = {record.option_code for record in records if record.option_code is not None}
    if data_type == "SINGLE_SELECT":
        if not isinstance(value, str) or value not in options:
            raise ValueError("Value is not an active option.")
        return value
    if data_type == "MULTI_SELECT":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("Value must be a list of options.")
        unique = sorted(set(value))
        if len(unique) != len(value):
            raise ValueError("Option values must not be duplicated.")
        if not set(unique) <= options:
            raise ValueError("Value contains an inactive or unknown option.")
        return unique
    if data_type == "JSON_OBJECT":
        if not isinstance(value, dict):
            raise ValueError("Value must be an object.")
        if len(json.dumps(value, separators=(",", ":"))) > 20_000:
            raise ValueError("Value is too large.")
        return value
    raise ValueError("Field type is not supported for ticket submission.")


def _validate_bounds(field: FormFieldRecord, value: Any, errors: dict[str, list[str]]) -> None:
    validation = field.validation if isinstance(field.validation, dict) else {}
    key = f"custom_fields.{field.field_code}"
    length = len(value) if isinstance(value, (str, list)) else None
    minimum_length = validation.get("minimum_length")
    maximum_length = validation.get("maximum_length")
    minimum_items = validation.get("minimum_items")
    maximum_items = validation.get("maximum_items")
    if isinstance(minimum_length, int) and length is not None and length < minimum_length:
        errors.setdefault(key, []).append(
            f"Value must contain at least {minimum_length} characters."
        )
    if isinstance(maximum_length, int) and length is not None and length > maximum_length:
        errors.setdefault(key, []).append(
            f"Value must contain at most {maximum_length} characters."
        )
    if isinstance(minimum_items, int) and isinstance(value, list) and len(value) < minimum_items:
        errors.setdefault(key, []).append(f"Select at least {minimum_items} options.")
    if isinstance(maximum_items, int) and isinstance(value, list) and len(value) > maximum_items:
        errors.setdefault(key, []).append(f"Select at most {maximum_items} options.")
    if field.data_type == "NUMBER":
        numeric = Decimal(value)
        minimum = validation.get("minimum")
        maximum = validation.get("maximum")
        if minimum is not None and numeric < Decimal(str(minimum)):
            errors.setdefault(key, []).append(f"Value must be at least {minimum}.")
        if maximum is not None and numeric > Decimal(str(maximum)):
            errors.setdefault(key, []).append(f"Value must be at most {maximum}.")
