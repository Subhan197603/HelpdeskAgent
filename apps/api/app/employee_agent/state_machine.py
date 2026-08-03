"""Explicit, fail-closed employee helpdesk agent state machine."""

from apps.api.app.employee_agent.models import AgentState


class InvalidAgentTransition(RuntimeError):
    pass


_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.NEW: frozenset({AgentState.COLLECTING_INFORMATION}),
    AgentState.COLLECTING_INFORMATION: frozenset(
        {AgentState.CLASSIFIED, AgentState.COLLECTING_TICKET_FIELDS}
    ),
    AgentState.CLASSIFIED: frozenset(
        {AgentState.SEARCHING_KNOWLEDGE, AgentState.COLLECTING_TICKET_FIELDS}
    ),
    AgentState.SEARCHING_KNOWLEDGE: frozenset(
        {AgentState.SOLUTION_PROPOSED, AgentState.COLLECTING_TICKET_FIELDS}
    ),
    AgentState.SOLUTION_PROPOSED: frozenset({AgentState.AWAITING_RESOLUTION_CONFIRMATION}),
    AgentState.AWAITING_RESOLUTION_CONFIRMATION: frozenset(
        {
            AgentState.COLLECTING_INFORMATION,
            AgentState.RESOLVED_WITHOUT_TICKET,
            AgentState.COLLECTING_TICKET_FIELDS,
        }
    ),
    AgentState.COLLECTING_TICKET_FIELDS: frozenset(
        {AgentState.COLLECTING_TICKET_FIELDS, AgentState.TICKET_DRAFT_READY}
    ),
    AgentState.TICKET_DRAFT_READY: frozenset({AgentState.AWAITING_USER_CONFIRMATION}),
    AgentState.AWAITING_USER_CONFIRMATION: frozenset({AgentState.TICKET_SUBMITTED}),
    AgentState.RESOLVED_WITHOUT_TICKET: frozenset(),
    AgentState.TICKET_SUBMITTED: frozenset(),
}


class EmployeeAgentStateMachine:
    def __init__(self, state: AgentState) -> None:
        self._state = state

    @property
    def state(self) -> AgentState:
        return self._state

    def advance(self, target: AgentState) -> AgentState:
        if target not in _TRANSITIONS[self._state]:
            raise InvalidAgentTransition(f"Invalid employee-agent transition to {target.value}")
        self._state = target
        return target
