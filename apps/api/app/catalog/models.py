"""Transport-independent catalogue records returned by narrow repositories."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ServiceProject:
    project_id: UUID
    project_key: str
    project_name: str
    description: str | None
    default_timezone: str


@dataclass(frozen=True, slots=True)
class ServiceNode:
    service_node_id: UUID
    parent_node_id: UUID | None
    node_code: str
    node_name: str
    node_type: str
    display_order: int
    criticality_code: str | None
    data_classification: str


@dataclass(frozen=True, slots=True)
class WorkType:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class RequestTypeVersion:
    request_type_version_id: UUID
    version_number: int
    effective_from: datetime | None
    effective_to: datetime | None
    effective_version_count: int


@dataclass(frozen=True, slots=True)
class RequestTypeSummary:
    request_type_id: UUID
    project_id: UUID
    request_type_code: str
    request_type_name: str
    portal_description: str | None
    portal_group: str | None
    display_order: int
    work_type: WorkType
    version: RequestTypeVersion


@dataclass(frozen=True, slots=True)
class FormFieldRecord:
    custom_field_id: UUID
    field_code: str
    field_name: str
    data_type: str
    display_label: str | None
    help_text: str | None
    display_order: int
    required: bool
    default_value: Any
    validation: Any
    condition: Any
    option_id: UUID | None
    option_code: str | None
    option_label: str | None
    option_display_order: int | None


@dataclass(frozen=True, slots=True)
class ApplicationEnvironmentReference:
    application_environment_id: UUID
    environment_code: str
    environment_name: str
    service_node_id: UUID | None
