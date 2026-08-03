"""Prometheus text-format exposition of in-process service counters."""

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from apps.api.app.core.exceptions import NotFoundError

router = APIRouter(prefix="/api/v1/observability", tags=["observability"])

_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _counter(lines: list[str], name: str, value: float, help_text: str) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} counter")
    lines.append(f"{name} {value:g}")


def _labeled(lines: list[str], name: str, labels: dict[str, int], key: str, help_text: str) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} counter")
    for label_value in sorted(labels):
        lines.append(f'{name}{{{key}="{label_value}"}} {labels[label_value]}')


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def prometheus_metrics(request: Request) -> PlainTextResponse:
    settings = request.app.state.settings
    if not settings.metrics_endpoint_enabled:
        raise NotFoundError("Metrics exposition is disabled.")
    tickets = request.app.state.ticket_metrics
    catalogue = request.app.state.catalogue_metrics
    copilot = request.app.state.copilot_metrics
    lines: list[str] = []
    _counter(
        lines,
        "helpdesk_tickets_submitted_total",
        tickets.tickets_submitted,
        "Tickets submitted through the deterministic workflow.",
    )
    _counter(
        lines,
        "helpdesk_ticket_idempotent_replays_total",
        tickets.idempotent_replays,
        "Idempotent ticket submissions replayed without side effects.",
    )
    _counter(
        lines,
        "helpdesk_ticket_authorization_denials_total",
        tickets.authorization_denials,
        "Ticket operations rejected by authorization.",
    )
    _counter(
        lines,
        "helpdesk_ticket_operation_duration_ms_total",
        tickets.operation_duration_ms_total,
        "Cumulative ticket service operation duration in milliseconds.",
    )
    _labeled(
        lines,
        "helpdesk_ticket_operations_total",
        tickets.operation_counts,
        "operation",
        "Ticket service operations by name.",
    )
    _labeled(
        lines,
        "helpdesk_catalogue_operations_total",
        catalogue.operation_counts,
        "operation",
        "Catalogue service operations by name.",
    )
    _counter(
        lines,
        "helpdesk_copilot_analyses_total",
        copilot.analyses,
        "Analyst copilot ticket analyses.",
    )
    _counter(
        lines,
        "helpdesk_copilot_drafts_created_total",
        copilot.drafts_created,
        "Analyst copilot drafts generated.",
    )
    _counter(
        lines,
        "helpdesk_copilot_drafts_posted_total",
        copilot.drafts_posted,
        "Copilot drafts posted by an analyst.",
    )
    _counter(
        lines,
        "helpdesk_copilot_drafts_resolved_total",
        copilot.drafts_resolved,
        "Copilot drafts used in an explicit resolve action.",
    )
    _counter(
        lines,
        "helpdesk_copilot_provider_failures_total",
        copilot.provider_failures,
        "Copilot provider calls that failed or were rejected by policy.",
    )
    _labeled(
        lines,
        "helpdesk_copilot_feedback_total",
        copilot.feedback_decisions,
        "decision",
        "Analyst copilot feedback decisions.",
    )
    return PlainTextResponse("\n".join(lines) + "\n", media_type=_CONTENT_TYPE)
