"""Top-level API routing."""

from fastapi import APIRouter

from apps.api.app.admin.api import router as admin_router
from apps.api.app.analyst_copilot.api import oversight_router as ai_oversight_router
from apps.api.app.analyst_copilot.api import router as analyst_copilot_router
from apps.api.app.api.health import router as health_router
from apps.api.app.approvals.api import router as approvals_router
from apps.api.app.attachments.api import router as attachments_router
from apps.api.app.catalog.api import router as catalogue_router
from apps.api.app.employee_agent.api import router as employee_agent_router
from apps.api.app.identity.api import router as identity_router
from apps.api.app.ingestion.api import router as ingestion_router
from apps.api.app.knowledge.api import router as knowledge_router
from apps.api.app.knowledge.document_api import router as knowledge_document_router
from apps.api.app.knowledge.reader_api import router as knowledge_reader_router
from apps.api.app.notifications.api import router as notifications_router
from apps.api.app.observability.api import router as observability_router
from apps.api.app.queues.api import router as queues_router
from apps.api.app.reporting.api import router as reporting_router
from apps.api.app.retrieval.api import router as retrieval_router
from apps.api.app.routing.api import router as routing_router
from apps.api.app.tickets.api import router as tickets_router
from apps.api.app.workflows.api import router as workflows_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(identity_router)
api_router.include_router(catalogue_router)
api_router.include_router(tickets_router)
api_router.include_router(workflows_router)
api_router.include_router(routing_router)
api_router.include_router(queues_router)
api_router.include_router(reporting_router)
api_router.include_router(attachments_router)
api_router.include_router(approvals_router)
api_router.include_router(notifications_router)
api_router.include_router(knowledge_router)
api_router.include_router(knowledge_document_router)
api_router.include_router(knowledge_reader_router)
api_router.include_router(ingestion_router)
api_router.include_router(retrieval_router)
api_router.include_router(employee_agent_router)
api_router.include_router(analyst_copilot_router)
api_router.include_router(ai_oversight_router)
api_router.include_router(admin_router)
api_router.include_router(observability_router)
