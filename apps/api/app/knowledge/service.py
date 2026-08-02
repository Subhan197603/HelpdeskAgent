"""Authorized knowledge-source administration and acquisition permission gate."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConcurrencyError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.knowledge.models import IdempotencyClaim, KnowledgeSource, SourceAuthorization
from apps.api.app.knowledge.repository import KnowledgeSourceRepository
from apps.api.app.knowledge.schemas import (
    AcquisitionAuthorizationCommand,
    AcquisitionAuthorizationResponse,
    AcquisitionMethod,
    AcquisitionPermissionResponse,
    ApprovalStatus,
    AudienceScope,
    SourceApprovalCommand,
    SourceCreate,
    SourceDefinition,
    SourceList,
    SourceResponse,
    SourceStatus,
    SourceType,
    SourceUpdate,
)

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]
_EXTERNAL_METHODS = {
    "APPROVED_DIRECT_DOWNLOAD",
    "API_FEED",
    "REPOSITORY_CONNECTOR",
}


class KnowledgeConfigurationError(ConflictError):
    error_code = "knowledge_source_configuration"


class KnowledgeSourceService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        settings: Settings,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._settings = settings

    async def list(
        self,
        context: RequestContext,
        *,
        source_type: str | None,
        audience: str | None,
        status: str | None,
        approval_status: str | None,
        limit: int,
    ) -> SourceList:
        self._authorize(context, Permission.KNOWLEDGE_SOURCE_READ_ADMIN)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            rows = await KnowledgeSourceRepository(uow.session).list(
                tenant_id,
                source_type=source_type,
                audience=audience,
                status=status,
                approval_status=approval_status,
                limit=limit,
            )
        return SourceList(items=[_response(row) for row in rows])

    async def get(self, context: RequestContext, source_id: UUID) -> SourceResponse:
        self._authorize(context, Permission.KNOWLEDGE_SOURCE_READ_ADMIN)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            source = await KnowledgeSourceRepository(uow.session).get(tenant_id, source_id)
        if source is None:
            raise NotFoundError("Knowledge source was not found.")
        return _response(source)

    async def create(
        self, context: RequestContext, command: SourceCreate, idempotency_key: str
    ) -> tuple[SourceResponse, bool]:
        self._authorize(context, Permission.KNOWLEDGE_SOURCE_CREATE)
        tenant_id, user_id = _identity(context)
        if command.scope == "GLOBAL":
            self._authorize(context, Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL)
        definition = _definition(command, canonical_location=_canonical(command))
        request_hash = _hash("create", command.model_dump(mode="json"))
        async with self._factory(context) as uow:
            repo = KnowledgeSourceRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_SOURCE_CREATE"
            )
            _validate_claim(claim, user_id, request_hash)
            if claim.processing_status == "COMPLETED":
                if claim.result_resource_id is None:
                    raise KnowledgeConfigurationError("Idempotent source result is unavailable.")
                source = await repo.get(tenant_id, UUID(claim.result_resource_id))
                if source is None:
                    raise KnowledgeConfigurationError("Idempotent source result is unavailable.")
                await uow.commit()
                return _response(source), True
            await _validate_references(repo, tenant_id, definition)
            source_id = await repo.create(
                None if command.scope == "GLOBAL" else tenant_id,
                user_id,
                definition,
                context.correlation_id,
                context.request_id,
            )
            await repo.complete_idempotency(claim.record_id, "KNOWLEDGE_SOURCE", source_id, 201)
            source = await repo.get(tenant_id, source_id)
            if source is None:
                raise KnowledgeConfigurationError("Created source is unavailable.")
            await uow.commit()
        return _response(source), False

    async def update(
        self,
        context: RequestContext,
        source_id: UUID,
        command: SourceUpdate,
        idempotency_key: str,
    ) -> tuple[SourceResponse, bool]:
        self._authorize(context, Permission.KNOWLEDGE_SOURCE_UPDATE)
        tenant_id, user_id = _identity(context)
        definition = _definition(command, canonical_location=_canonical(command))
        request_hash = _hash(
            "update", {"source_id": str(source_id), **command.model_dump(mode="json")}
        )
        async with self._factory(context) as uow:
            repo = KnowledgeSourceRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_SOURCE_UPDATE"
            )
            _validate_claim(claim, user_id, request_hash)
            current = await repo.get(tenant_id, source_id, lock=True)
            if current is None:
                raise NotFoundError("Knowledge source was not found.")
            if current.tenant_id is None:
                self._authorize(context, Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL)
            if claim.processing_status == "COMPLETED":
                await uow.commit()
                return _response(current), True
            await _validate_references(repo, tenant_id, definition)
            if not await repo.update(
                tenant_id,
                source_id,
                user_id,
                definition,
                command.expected_version,
                context.correlation_id,
                context.request_id,
            ):
                raise ConcurrencyError("Knowledge source row version is stale.")
            await repo.complete_idempotency(claim.record_id, "KNOWLEDGE_SOURCE", source_id, 200)
            source = await repo.get(tenant_id, source_id)
            if source is None:
                raise KnowledgeConfigurationError("Updated source is unavailable.")
            await uow.commit()
        return _response(source), False

    async def approve(
        self,
        context: RequestContext,
        source_id: UUID,
        command: SourceApprovalCommand,
        idempotency_key: str,
    ) -> tuple[SourceResponse, bool]:
        self._authorize(context, Permission.KNOWLEDGE_SOURCE_APPROVE)
        tenant_id, user_id = _identity(context)
        request_hash = _hash(
            "approval", {"source_id": str(source_id), **command.model_dump(mode="json")}
        )
        async with self._factory(context) as uow:
            repo = KnowledgeSourceRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_SOURCE_APPROVAL"
            )
            _validate_claim(claim, user_id, request_hash)
            current = await repo.get(tenant_id, source_id, lock=True)
            if current is None:
                raise NotFoundError("Knowledge source was not found.")
            if current.tenant_id is None:
                self._authorize(context, Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL)
            if current.owner_user_id == user_id or (
                current.owner_group_id is not None
                and current.owner_group_id in context.support_group_ids
            ):
                raise AuthorizationError("A source owner cannot approve the same source.")
            if claim.processing_status == "COMPLETED":
                await uow.commit()
                return _response(current), True
            if not await repo.decide_approval(
                tenant_id,
                source_id,
                user_id,
                command.decision,
                command.expected_version,
                context.correlation_id,
                context.request_id,
            ):
                raise ConcurrencyError("Knowledge source approval state or version changed.")
            await repo.complete_idempotency(claim.record_id, "KNOWLEDGE_SOURCE", source_id, 200)
            source = await repo.get(tenant_id, source_id)
            if source is None:
                raise KnowledgeConfigurationError("Approved source is unavailable.")
            await uow.commit()
        return _response(source), False

    async def authorize_acquisition(
        self,
        context: RequestContext,
        source_id: UUID,
        command: AcquisitionAuthorizationCommand,
        idempotency_key: str,
    ) -> AcquisitionAuthorizationResponse:
        self._authorize(context, Permission.KNOWLEDGE_ACQUISITION_PERMISSION_MANAGE)
        tenant_id, user_id = _identity(context)
        request_hash = _hash(
            "acquisition-authorization",
            {"source_id": str(source_id), **command.model_dump(mode="json")},
        )
        async with self._factory(context) as uow:
            repo = KnowledgeSourceRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id,
                user_id,
                idempotency_key,
                request_hash,
                "KNOWLEDGE_SOURCE_ACQUISITION_AUTHORIZATION",
            )
            _validate_claim(claim, user_id, request_hash)
            source = await repo.get(tenant_id, source_id, lock=True)
            if source is None:
                raise NotFoundError("Knowledge source was not found.")
            if source.tenant_id is None:
                self._authorize(context, Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL)
            if claim.processing_status == "COMPLETED":
                if claim.result_resource_id is None:
                    raise KnowledgeConfigurationError("Authorization result is unavailable.")
                authorization = await repo.authorization(tenant_id, UUID(claim.result_resource_id))
                if authorization is None:
                    raise KnowledgeConfigurationError("Authorization result is unavailable.")
                await uow.commit()
                return _authorization_response(authorization, source, replayed=True)
            if source.row_version != command.expected_version:
                raise ConcurrencyError("Knowledge source row version is stale.")
            if command.acquisition_method != source.acquisition_method:
                raise ValidationError(
                    "Authorization method must match the configured source method."
                )
            authorization_id = await repo.authorize_acquisition(
                tenant_id,
                source,
                user_id,
                decision=command.decision,
                acquisition_method=command.acquisition_method,
                permission_reference=command.permission_reference.strip(),
                valid_from=command.valid_from,
                valid_to=command.valid_to,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
            )
            if authorization_id is None:
                raise KnowledgeConfigurationError(
                    "Only an active, approved source can receive acquisition permission."
                )
            await repo.complete_idempotency(
                claim.record_id, "SOURCE_ACQUISITION_AUTHORIZATION", authorization_id, 201
            )
            authorization = await repo.authorization(tenant_id, authorization_id)
            updated = await repo.get(tenant_id, source_id)
            if authorization is None or updated is None:
                raise KnowledgeConfigurationError("Authorization result is unavailable.")
            await uow.commit()
        return _authorization_response(authorization, updated, replayed=False)

    async def permission(
        self, context: RequestContext, source_id: UUID
    ) -> AcquisitionPermissionResponse:
        self._authorize(context, Permission.KNOWLEDGE_SOURCE_READ_ADMIN)
        tenant_id, _ = _identity(context)
        evaluated_at = datetime.now(UTC)
        async with self._factory(context) as uow:
            repo = KnowledgeSourceRepository(uow.session)
            source = await repo.get(tenant_id, source_id)
            if source is None:
                raise NotFoundError("Knowledge source was not found.")
            authorization = await repo.effective_authorization(tenant_id, source)
        reasons = acquisition_permission_reasons(source, authorization, self._settings)
        return AcquisitionPermissionResponse(
            source_id=source_id,
            allowed=not reasons,
            reasons=reasons,
            evaluated_at=evaluated_at,
        )

    def _authorize(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError()


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise AuthorizationError()
    return context.tenant_id, context.user_id


def _canonical(command: SourceDefinition) -> str:
    value = command.canonical_location.strip()
    parsed = urlsplit(value)
    allowed_schemes = {"https", "manual", "repository", "s3"}
    if parsed.scheme.lower() not in allowed_schemes:
        raise ValidationError("Canonical location uses an unsupported scheme.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError("Canonical location cannot contain credentials, query, or fragment.")
    if command.source_type in {"ORACLE_PUBLIC_DOCUMENTATION", "OTHER_EXTERNAL"} and (
        parsed.scheme.lower() != "https" or not parsed.hostname
    ):
        raise ValidationError("External sources require a canonical HTTPS location.")
    if parsed.scheme.lower() in {"https", "s3"} and not parsed.netloc:
        raise ValidationError("Canonical location requires a host or bucket.")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "", "", ""))


def _definition(command: SourceDefinition, *, canonical_location: str) -> SourceDefinition:
    values = command.model_dump(exclude={"scope", "expected_version"})
    values["canonical_location"] = canonical_location
    return SourceDefinition.model_validate(values)


async def _validate_references(
    repo: KnowledgeSourceRepository, tenant_id: UUID, definition: SourceDefinition
) -> None:
    if definition.owner_user_id is not None and not await repo.reference_exists(
        "identity.app_user", "user_id", definition.owner_user_id, tenant_id
    ):
        raise ValidationError("Source owner user is not active in the tenant.")
    if definition.owner_group_id is not None and not await repo.reference_exists(
        "identity.support_group", "support_group_id", definition.owner_group_id, tenant_id
    ):
        raise ValidationError("Source owner group is not in the tenant.")
    if definition.product_node_id is not None:
        if not await repo.reference_exists(
            "kb.product_node", "product_node_id", definition.product_node_id, tenant_id
        ):
            raise ValidationError("Product node is outside the permitted scope.")
        if await repo.product_level(definition.product_node_id) == "MODULE":
            raise ValidationError("Product metadata cannot reference a module node.")
    if definition.module_node_id is not None:
        if not await repo.reference_exists(
            "kb.product_node", "product_node_id", definition.module_node_id, tenant_id
        ):
            raise ValidationError("Module node is outside the permitted scope.")
        if await repo.product_level(definition.module_node_id) != "MODULE":
            raise ValidationError("Module metadata must reference a module node.")
    if definition.release_id is not None and not await repo.release_exists(definition.release_id):
        raise ValidationError("Knowledge release was not found.")


def _validate_claim(claim: IdempotencyClaim, user_id: UUID, request_hash: str) -> None:
    if claim.principal_id != str(user_id) or claim.request_hash != request_hash:
        raise ConflictError("Idempotency key was already used for another request.")
    if claim.processing_status not in {"IN_PROGRESS", "COMPLETED"}:
        raise ConflictError("Idempotent operation cannot be resumed.")


def _hash(operation: str, value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            {"operation": operation, **value}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class AcquisitionGateSettings(Protocol):
    oracle_document_acquisition_enabled: bool


def acquisition_permission_reasons(
    source: KnowledgeSource,
    authorization: SourceAuthorization | None,
    settings: AcquisitionGateSettings,
    *,
    external: bool = True,
) -> list[str]:
    reasons: list[str] = []
    if source.source_status != "ACTIVE":
        reasons.append("SOURCE_NOT_ACTIVE")
    if source.approval_status != "APPROVED":
        reasons.append("SOURCE_NOT_APPROVED")
    if external and source.acquisition_method not in _EXTERNAL_METHODS:
        reasons.append("EXTERNAL_ACQUISITION_NOT_CONFIGURED")
    if external and not source.automated_access_allowed:
        reasons.append("AUTOMATED_ACCESS_NOT_AUTHORIZED")
    if external and (authorization is None or authorization.decision_code != "APPROVED"):
        reasons.append("APPROVED_ALLOWLIST_ENTRY_MISSING")
    elif (
        external
        and authorization is not None
        and (authorization.acquisition_method != source.acquisition_method)
    ):
        reasons.append("ALLOWLIST_METHOD_MISMATCH")
    if external and (
        source.source_type == "ORACLE_PUBLIC_DOCUMENTATION"
        and not settings.oracle_document_acquisition_enabled
    ):
        reasons.append("ORACLE_AUTOMATED_ACQUISITION_DISABLED")
    return reasons


def _response(value: KnowledgeSource) -> SourceResponse:
    return SourceResponse(
        id=value.source_id,
        scope="GLOBAL" if value.tenant_id is None else "TENANT",
        code=value.source_code,
        name=value.source_name,
        source_type=cast("SourceType", value.source_type),
        publisher_name=value.publisher_name,
        canonical_location=value.canonical_location,
        acquisition_method=cast("AcquisitionMethod", value.acquisition_method),
        automated_access_allowed=value.automated_access_allowed,
        permission_reference=value.permission_reference,
        audience_scope=cast("AudienceScope", value.audience_scope),
        status=cast("SourceStatus", value.source_status),
        approval_status=cast("ApprovalStatus", value.approval_status),
        owner_user_id=value.owner_user_id,
        owner_group_id=value.owner_group_id,
        product_node_id=value.product_node_id,
        product_code=value.product_code,
        module_node_id=value.module_node_id,
        module_code=value.module_code,
        release_id=value.release_id,
        release_family=value.release_family,
        release_code=value.release_code,
        language_code=value.language_code,
        approved_by=value.approved_by,
        approved_at=value.approved_at,
        row_version=value.row_version,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _authorization_response(
    value: SourceAuthorization, source: KnowledgeSource, *, replayed: bool
) -> AcquisitionAuthorizationResponse:
    return AcquisitionAuthorizationResponse(
        id=value.authorization_id,
        decision=cast("Literal['APPROVED', 'REVOKED']", value.decision_code),
        acquisition_method=value.acquisition_method,
        permission_reference=value.permission_reference,
        valid_from=value.valid_from,
        valid_to=value.valid_to,
        decided_by=value.decided_by,
        decided_at=value.decided_at,
        source=_response(source),
        replayed=replayed,
    )
