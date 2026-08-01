"""Stable public response contracts for catalogue and dynamic forms."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from apps.api.app.catalog.rules import ConditionalRule

CatalogueFieldType = Literal[
    "TEXT",
    "LONG_TEXT",
    "NUMBER",
    "DATE",
    "TIMESTAMP",
    "BOOLEAN",
    "SINGLE_SELECT",
    "MULTI_SELECT",
    "USER",
    "GROUP",
    "SERVICE",
    "MODULE",
    "ASSET",
    "JSON_OBJECT",
]


class PageMetadata(BaseModel):
    limit: int
    offset: int
    returned: int


class ProjectResponse(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    default_timezone: str


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    page: PageMetadata


class ServiceNodeResponse(BaseModel):
    id: UUID
    parent_id: UUID | None
    code: str
    name: str
    node_type: str
    display_order: int
    criticality: str | None
    data_classification: str


class ServiceNodeListResponse(BaseModel):
    project_id: UUID
    parent_id: UUID | None
    items: list[ServiceNodeResponse]
    page: PageMetadata


class WorkTypeResponse(BaseModel):
    code: str
    name: str


class RequestTypeResponse(BaseModel):
    id: UUID
    version_id: UUID
    version_number: int
    code: str
    name: str
    description: str | None
    portal_group: str | None
    display_order: int
    work_type: WorkTypeResponse
    effective_from: datetime | None
    effective_to: datetime | None


class RequestTypeListResponse(BaseModel):
    project_id: UUID
    evaluated_at: datetime
    items: list[RequestTypeResponse]
    page: PageMetadata


class FieldValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_length: int | None = Field(default=None, ge=0)
    maximum_length: int | None = Field(default=None, ge=1)
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    minimum_items: int | None = Field(default=None, ge=0)
    maximum_items: int | None = Field(default=None, ge=1)
    pattern: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_bounds(self) -> "FieldValidationResponse":
        if (
            self.minimum_length is not None
            and self.maximum_length is not None
            and self.minimum_length > self.maximum_length
        ):
            raise ValueError("minimum_length cannot exceed maximum_length")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if (
            self.minimum_items is not None
            and self.maximum_items is not None
            and self.minimum_items > self.maximum_items
        ):
            raise ValueError("minimum_items cannot exceed maximum_items")
        return self


class FieldOptionResponse(BaseModel):
    id: UUID
    value: str
    label: str
    display_order: int


class FormFieldResponse(BaseModel):
    field_id: UUID
    field_code: str
    data_type: CatalogueFieldType
    label: str
    description: str | None
    required: bool
    display_order: int
    default_value: JsonValue = None
    validation: FieldValidationResponse
    condition: ConditionalRule | None
    options: list[FieldOptionResponse]


class RequestFormResponse(BaseModel):
    request_type_id: UUID
    request_type_version_id: UUID
    version_number: int
    code: str
    name: str
    description: str | None
    evaluated_at: datetime
    effective_from: datetime | None
    effective_to: datetime | None
    project: ProjectResponse
    work_type: WorkTypeResponse
    fields: list[FormFieldResponse]


class ProblemResponse(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    correlation_id: str
    errors: dict[str, list[str]] | None = None
