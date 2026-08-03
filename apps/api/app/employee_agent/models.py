"""Internal employee-agent state, conversation, citation, and stream contracts."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID


class AgentState(StrEnum):
    NEW = "NEW"
    COLLECTING_INFORMATION = "COLLECTING_INFORMATION"
    CLASSIFIED = "CLASSIFIED"
    SEARCHING_KNOWLEDGE = "SEARCHING_KNOWLEDGE"
    SOLUTION_PROPOSED = "SOLUTION_PROPOSED"
    AWAITING_RESOLUTION_CONFIRMATION = "AWAITING_RESOLUTION_CONFIRMATION"
    RESOLVED_WITHOUT_TICKET = "RESOLVED_WITHOUT_TICKET"
    COLLECTING_TICKET_FIELDS = "COLLECTING_TICKET_FIELDS"
    TICKET_DRAFT_READY = "TICKET_DRAFT_READY"
    AWAITING_USER_CONFIRMATION = "AWAITING_USER_CONFIRMATION"
    TICKET_SUBMITTED = "TICKET_SUBMITTED"


class TurnOutcome(StrEnum):
    RESOLUTION_PROPOSED = "RESOLUTION_PROPOSED"
    ESCALATION_RECOMMENDED = "ESCALATION_RECOMMENDED"
    SAFE_REFUSAL = "SAFE_REFUSAL"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class Conversation:
    conversation_id: UUID
    state: AgentState


@dataclass(frozen=True, slots=True)
class StartedTurn:
    turn_id: UUID
    user_message_id: UUID
    prior_messages: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class Citation:
    label: str
    document_title: str
    source_type: str
    canonical_uri: str
    section_title: str | None
    section_anchor: str | None
    page_number: int | None


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    text: str
    state: AgentState
    outcome: TurnOutcome
    citations: tuple[Citation, ...] = ()
    retrieval_configuration_version_id: UUID | None = None
    agent_run_id: UUID | None = None
    evidence: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class StreamEvent:
    event: str
    data: dict[str, Any]
