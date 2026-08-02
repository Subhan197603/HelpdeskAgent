"""Outbox-driven, retry-safe email and in-app notification worker."""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.app.core.context import RequestContext
from apps.api.app.db.transaction_context import apply_transaction_context
from apps.api.app.notifications.rendering import UnsafeTemplate, render_template
from apps.worker.worker.settings import WorkerSettings

logger = logging.getLogger(__name__)
_EVENT_TYPES = (
    "NOTIFY_TICKET_CREATED",
    "NOTIFY_TICKET_ASSIGNED",
    "NOTIFY_AGENT_PUBLIC_RESPONSE_ADDED",
    "NOTIFY_CUSTOMER_COMMENT_ADDED",
    "NOTIFY_STATUS_CHANGED",
    "APPROVAL_REQUESTED",
    "APPROVAL_DECIDED",
    "APPROVAL_CANCELLED",
    "APPROVAL_EXPIRED",
    "SLA_WARNING",
    "SLA_BREACHED",
)
_VARIABLES = frozenset({"ticket_key", "recipient_name", "event_name", "status_name", "action_url"})


class PermanentNotificationError(RuntimeError):
    """A configuration or recipient problem that cannot succeed on retry."""


class RetryableNotificationError(RuntimeError):
    """A transient provider problem."""


class EmailSender(Protocol):
    async def send(
        self, *, to_address: str, subject: str, body: str, html_content: bool, message_id: str
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class OutboxNotification:
    outbox_event_id: UUID
    tenant_id: UUID
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Recipient:
    user_id: UUID
    display_name: str
    email_address: str


@dataclass(frozen=True, slots=True)
class TemplateVersion:
    version_id: UUID
    channel_code: str
    subject: str | None
    body: str
    content_type: str


@dataclass(frozen=True, slots=True)
class PendingDelivery:
    delivery_id: UUID
    tenant_id: UUID
    recipient: str
    subject: str
    body: str
    content_type: str
    attempt_count: int


class SmtpEmailSender:
    def __init__(self, settings: WorkerSettings) -> None:
        self._settings = settings

    async def send(
        self, *, to_address: str, subject: str, body: str, html_content: bool, message_id: str
    ) -> str:
        header_values = (
            to_address,
            subject,
            message_id,
            self._settings.smtp_from,
        )
        if any("\r" in value or "\n" in value for value in header_values):
            raise PermanentNotificationError("Email headers contain forbidden line breaks.")
        return await asyncio.to_thread(
            self._send_sync,
            to_address,
            subject,
            body,
            html_content,
            message_id,
        )

    def _send_sync(
        self, to_address: str, subject: str, body: str, html_content: bool, message_id: str
    ) -> str:
        message = EmailMessage()
        message["From"] = self._settings.smtp_from
        message["To"] = to_address
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = message_id
        message.set_content(body, subtype="html" if html_content else "plain")
        try:
            with smtplib.SMTP(
                self._settings.smtp_host,
                self._settings.smtp_port,
                timeout=self._settings.smtp_timeout_seconds,
            ) as client:
                if self._settings.smtp_starttls:
                    client.starttls()
                username = self._settings.smtp_username
                password = self._settings.smtp_password.get_secret_value()
                if username:
                    client.login(username, password)
                client.send_message(message)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
            raise PermanentNotificationError(type(exc).__name__) from None
        except (OSError, smtplib.SMTPException) as exc:
            raise RetryableNotificationError(type(exc).__name__) from None
        return message_id


class NotificationWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: WorkerSettings,
        sender: EmailSender | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._sender = sender or SmtpEmailSender(settings)

    async def process_one(self) -> bool:
        if await self.plan_one():
            return True
        return await self.deliver_one()

    async def plan_one(self) -> bool:
        event_id: UUID | None = None
        try:
            async with self._sessions() as session, session.begin():
                event = await _claim_event(session, self._settings.worker_id)
                if event is None:
                    return False
                event_id = event.outbox_event_id
                await _context(session, event.tenant_id, event.outbox_event_id, "notification-plan")
                await _plan(session, event)
                await session.execute(
                    text("""
                        UPDATE integration.outbox_event
                        SET status_code='PROCESSED',processed_at=clock_timestamp(),
                          locked_at=NULL,locked_by=NULL,last_error=NULL
                        WHERE outbox_event_id=:event_id AND status_code='PROCESSING'
                    """),
                    {"event_id": event.outbox_event_id},
                )
            return True
        except PermanentNotificationError as error:
            await self._fail_event(event_id, type(error).__name__, final=True)
            return True
        except Exception as error:
            logger.exception(
                "Notification planning failed",
                extra={"event_id": str(event_id) if event_id else None},
            )
            await self._fail_event(event_id, type(error).__name__, final=False)
            return True

    async def deliver_one(self) -> bool:
        delivery = await self._claim_delivery()
        if delivery is None:
            return False
        message_id = (
            f"<notification.{delivery.delivery_id}@{self._settings.smtp_message_id_domain}>"
        )
        try:
            provider_id = await self._sender.send(
                to_address=delivery.recipient,
                subject=delivery.subject,
                body=delivery.body,
                html_content=delivery.content_type == "HTML",
                message_id=message_id,
            )
        except PermanentNotificationError as error:
            await self._finish_delivery(delivery, "PERMANENT_FAILURE", None, type(error).__name__)
        except Exception as error:
            logger.warning(
                "Email delivery failed",
                extra={
                    "delivery_id": str(delivery.delivery_id),
                    "error_code": type(error).__name__,
                },
            )
            await self._finish_delivery(delivery, "RETRYABLE_FAILURE", None, type(error).__name__)
        else:
            await self._finish_delivery(delivery, "DELIVERED", provider_id, None)
        return True

    async def _claim_delivery(self) -> PendingDelivery | None:
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    text("""
                        WITH candidate AS (
                          SELECT notification_delivery_id
                          FROM integration.notification_delivery
                          WHERE NOT final_failure AND (
                            (delivery_status IN ('PENDING','FAILED')
                              AND next_attempt_at<=clock_timestamp()) OR
                            (delivery_status='SENDING'
                              AND locked_at<clock_timestamp()-interval '5 minutes')
                          )
                          ORDER BY next_attempt_at,created_at,notification_delivery_id
                          FOR UPDATE SKIP LOCKED LIMIT 1
                        )
                        UPDATE integration.notification_delivery AS delivery
                        SET delivery_status='SENDING',locked_at=clock_timestamp(),
                          locked_by=:worker_id
                        FROM candidate
                        WHERE delivery.notification_delivery_id=
                          candidate.notification_delivery_id
                        RETURNING delivery.notification_delivery_id,delivery.tenant_id,
                          delivery.recipient_reference,delivery.rendered_subject,
                          delivery.rendered_body,
                          (SELECT content_type FROM config.notification_template_version
                            WHERE notification_template_version_id=
                              delivery.notification_template_version_id),
                          delivery.attempt_count
                    """),
                    {"worker_id": self._settings.worker_id},
                )
            ).one_or_none()
            return PendingDelivery(*tuple(row)) if row is not None else None

    async def _finish_delivery(
        self,
        delivery: PendingDelivery,
        outcome: str,
        provider_id: str | None,
        error_code: str | None,
    ) -> None:
        next_count = delivery.attempt_count + 1
        final = outcome == "PERMANENT_FAILURE" or next_count >= self._settings.worker_max_attempts
        delay = min(300, 2**next_count + delivery.delivery_id.int % 7)
        async with self._sessions() as session, session.begin():
            await _context(session, delivery.tenant_id, delivery.delivery_id, "notification-send")
            await session.execute(
                text("""
                    INSERT INTO integration.notification_delivery_attempt(
                      tenant_id,notification_delivery_id,attempt_number,outcome_code,
                      provider_message_id,error_code)
                    VALUES (:tenant_id,:delivery_id,:attempt,:outcome,:provider_id,:error_code)
                    ON CONFLICT (notification_delivery_id,attempt_number) DO NOTHING
                """),
                {
                    "tenant_id": delivery.tenant_id,
                    "delivery_id": delivery.delivery_id,
                    "attempt": next_count,
                    "outcome": outcome,
                    "provider_id": provider_id,
                    "error_code": error_code,
                },
            )
            await session.execute(
                text("""
                    UPDATE integration.notification_delivery
                    SET delivery_status=CASE WHEN :outcome='DELIVERED'
                          THEN 'DELIVERED' ELSE 'FAILED' END,
                      attempt_count=:attempt,provider_message_id=:provider_id,
                      last_error=:error_code,final_failure=:final,
                      next_attempt_at=clock_timestamp()+make_interval(secs=>:delay),
                      delivered_at=CASE WHEN :outcome='DELIVERED'
                        THEN clock_timestamp() ELSE NULL END,
                      locked_at=NULL,locked_by=NULL
                    WHERE notification_delivery_id=:delivery_id
                      AND delivery_status='SENDING'
                """),
                {
                    "delivery_id": delivery.delivery_id,
                    "outcome": outcome,
                    "attempt": next_count,
                    "provider_id": provider_id,
                    "error_code": error_code,
                    "final": final,
                    "delay": delay,
                },
            )

    async def _fail_event(self, event_id: UUID | None, error_code: str, *, final: bool) -> None:
        if event_id is None:
            return
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("""
                    UPDATE integration.outbox_event
                    SET retry_count=retry_count+1,
                      status_code=CASE WHEN :final OR retry_count+1>=:max_attempts
                        THEN 'DEAD_LETTER' ELSE 'FAILED' END,
                      available_at=clock_timestamp()
                        + make_interval(secs=>LEAST(300,POWER(2,retry_count)::integer)),
                      locked_at=NULL,locked_by=NULL,last_error=:error_code
                    WHERE outbox_event_id=:event_id AND status_code='PROCESSING'
                """),
                {
                    "event_id": event_id,
                    "final": final,
                    "max_attempts": self._settings.worker_max_attempts,
                    "error_code": error_code[:100],
                },
            )


async def _claim_event(session: AsyncSession, worker_id: str) -> OutboxNotification | None:
    row = (
        await session.execute(
            text("""
                WITH candidate AS (
                  SELECT outbox_event_id FROM integration.outbox_event
                  WHERE status_code IN ('PENDING','FAILED')
                    AND available_at<=clock_timestamp()
                    AND event_type=ANY(CAST(:event_types AS varchar[]))
                  ORDER BY created_at,outbox_event_id
                  FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE integration.outbox_event AS event
                SET status_code='PROCESSING',locked_at=clock_timestamp(),locked_by=:worker_id
                FROM candidate WHERE event.outbox_event_id=candidate.outbox_event_id
                RETURNING event.outbox_event_id,event.tenant_id,event.aggregate_type,
                  event.aggregate_id,event.event_type,event.payload_json
            """),
            {"event_types": list(_EVENT_TYPES), "worker_id": worker_id},
        )
    ).one_or_none()
    if row is None:
        return None
    if row.tenant_id is None:
        raise PermanentNotificationError("Notification event must be tenant-scoped.")
    return OutboxNotification(
        row.outbox_event_id,
        row.tenant_id,
        row.aggregate_type,
        row.aggregate_id,
        row.event_type,
        dict(row.payload_json),
    )


async def _plan(session: AsyncSession, event: OutboxNotification) -> None:
    ticket_id = _ticket_id(event)
    ticket = (
        await session.execute(
            text("""
                SELECT ticket.ticket_id,ticket.ticket_key,status.status_code,
                  coalesce(status.customer_visible_name,status.status_name) status_name,
                  ticket.reporter_user_id,ticket.requested_for_user_id,
                  ticket.assignee_user_id
                FROM itsm.ticket AS ticket
                JOIN config.workflow_status AS status ON status.status_id=ticket.status_id
                WHERE ticket.tenant_id=:tenant_id AND ticket.ticket_id=:ticket_id
            """),
            {"tenant_id": event.tenant_id, "ticket_id": ticket_id},
        )
    ).one_or_none()
    if ticket is None:
        raise PermanentNotificationError("Notification ticket was not found.")
    template_code = _template_code(event.event_type, ticket.status_code)
    recipients = await _recipients(session, event, ticket)
    if not recipients:
        raise PermanentNotificationError("Notification has no authorized active recipient.")
    action_url = f"/tickets/{ticket.ticket_key}"
    event_name = template_code.replace("_", " ").title()
    for recipient in recipients:
        values = {
            "ticket_key": ticket.ticket_key,
            "recipient_name": recipient.display_name,
            "event_name": event_name,
            "status_name": ticket.status_name,
            "action_url": action_url,
        }
        for channel in ("EMAIL", "PORTAL"):
            template = await _template(session, event.tenant_id, f"{template_code}_{channel}")
            if template.channel_code != channel:
                raise PermanentNotificationError("Notification template channel is inconsistent.")
            if template.content_type not in {"TEXT", "HTML"}:
                raise PermanentNotificationError("Notification content type is unsupported.")
            try:
                subject = (
                    render_template(template.subject or "", values, _VARIABLES, html_content=False)
                    if template.subject is not None
                    else None
                )
                body = render_template(
                    template.body,
                    values,
                    _VARIABLES,
                    html_content=template.content_type == "HTML",
                )
            except UnsafeTemplate as exc:
                raise PermanentNotificationError(str(exc)) from None
            deduplication_key = (
                f"{event.outbox_event_id}:{recipient.user_id}:{template.version_id}:{channel}"
            )
            if channel == "EMAIL":
                if subject is None:
                    raise PermanentNotificationError("Email template subject is required.")
                await session.execute(
                    text("""
                        INSERT INTO integration.notification_delivery(
                          tenant_id,notification_template_version_id,resource_type,
                          resource_id,recipient_reference,recipient_user_id,
                          outbox_event_id,channel_code,deduplication_key,
                          rendered_subject,rendered_body)
                        VALUES (:tenant_id,:version_id,'TICKET',CAST(:ticket_id AS varchar),
                          :email,:user_id,:event_id,'EMAIL',:deduplication_key,
                          :subject,:body)
                        ON CONFLICT (tenant_id,deduplication_key)
                          WHERE deduplication_key IS NOT NULL DO NOTHING
                    """),
                    {
                        "tenant_id": event.tenant_id,
                        "version_id": template.version_id,
                        "ticket_id": ticket_id,
                        "email": recipient.email_address,
                        "user_id": recipient.user_id,
                        "event_id": event.outbox_event_id,
                        "deduplication_key": deduplication_key,
                        "subject": subject,
                        "body": body,
                    },
                )
            else:
                await session.execute(
                    text("""
                        INSERT INTO integration.in_app_notification(
                          tenant_id,recipient_user_id,notification_template_version_id,
                          outbox_event_id,resource_type,resource_id,title,body,action_url)
                        VALUES (:tenant_id,:user_id,:version_id,:event_id,'TICKET',
                          CAST(:ticket_id AS varchar),:title,:body,:action_url)
                        ON CONFLICT (outbox_event_id,recipient_user_id,
                          notification_template_version_id) DO NOTHING
                    """),
                    {
                        "tenant_id": event.tenant_id,
                        "user_id": recipient.user_id,
                        "version_id": template.version_id,
                        "event_id": event.outbox_event_id,
                        "ticket_id": ticket_id,
                        "title": subject or event_name,
                        "body": body,
                        "action_url": action_url,
                    },
                )


def _ticket_id(event: OutboxNotification) -> UUID:
    value = event.payload.get("ticket_id")
    if value is None and event.aggregate_type == "TICKET":
        value = event.aggregate_id
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise PermanentNotificationError("Notification event has no valid ticket ID.") from None


def _template_code(event_type: str, status_code: str) -> str:
    mapping = {
        "NOTIFY_TICKET_CREATED": "TICKET_CREATED",
        "NOTIFY_TICKET_ASSIGNED": "TICKET_ASSIGNED",
        "NOTIFY_AGENT_PUBLIC_RESPONSE_ADDED": "PUBLIC_COMMENT_ADDED",
        "NOTIFY_CUSTOMER_COMMENT_ADDED": "PUBLIC_COMMENT_ADDED",
        "APPROVAL_REQUESTED": "APPROVAL_REQUESTED",
        "APPROVAL_DECIDED": "APPROVAL_DECIDED",
        "APPROVAL_CANCELLED": "APPROVAL_DECIDED",
        "APPROVAL_EXPIRED": "APPROVAL_DECIDED",
        "SLA_WARNING": "SLA_WARNING",
        "SLA_BREACHED": "SLA_BREACHED",
    }
    if event_type == "NOTIFY_STATUS_CHANGED":
        if status_code == "RESOLVED":
            return "TICKET_RESOLVED"
        if status_code == "CLOSED":
            return "TICKET_CLOSED"
        return "STATUS_CHANGED"
    try:
        return mapping[event_type]
    except KeyError:
        raise PermanentNotificationError("Notification event type is unsupported.") from None


async def _recipients(
    session: AsyncSession, event: OutboxNotification, ticket: Any
) -> list[Recipient]:
    if event.event_type == "APPROVAL_REQUESTED":
        try:
            approval_id = UUID(event.aggregate_id)
        except ValueError:
            raise PermanentNotificationError("Approval event has no valid approval ID.") from None
        rows = (
            await session.execute(
                text("""
                    SELECT DISTINCT user_record.user_id,user_record.display_name,
                      user_record.email_address
                    FROM itsm.ticket_approver AS approver
                    JOIN identity.app_user AS user_record
                      ON user_record.user_id=approver.approver_user_id
                     AND user_record.tenant_id=approver.tenant_id
                    WHERE approver.tenant_id=:tenant_id
                      AND approver.ticket_approval_id=:approval_id
                      AND approver.decision_code IS NULL AND user_record.active_flag
                """),
                {"tenant_id": event.tenant_id, "approval_id": approval_id},
            )
        ).all()
    else:
        if event.event_type in {
            "NOTIFY_TICKET_ASSIGNED",
            "NOTIFY_CUSTOMER_COMMENT_ADDED",
            "SLA_WARNING",
            "SLA_BREACHED",
        }:
            user_id = ticket.assignee_user_id
        else:
            user_id = ticket.requested_for_user_id or ticket.reporter_user_id
        actor = event.payload.get("actor_user_id")
        if user_id is None or (actor is not None and str(user_id) == str(actor)):
            return []
        rows = (
            await session.execute(
                text("""
                    SELECT user_id,display_name,email_address FROM identity.app_user
                    WHERE tenant_id=:tenant_id AND user_id=:user_id AND active_flag
                """),
                {"tenant_id": event.tenant_id, "user_id": user_id},
            )
        ).all()
    return [Recipient(*tuple(row)) for row in rows]


async def _template(session: AsyncSession, tenant_id: UUID, code: str) -> TemplateVersion:
    row = (
        await session.execute(
            text("""
                SELECT version.notification_template_version_id,version.channel_code,
                  version.subject_template,version.body_template,version.content_type
                FROM config.notification_template AS template
                JOIN config.notification_template_version AS version
                  ON version.notification_template_id=template.notification_template_id
                WHERE template.template_code=:code AND template.active_flag
                  AND (template.tenant_id=:tenant_id OR template.tenant_id IS NULL)
                  AND version.version_status='PUBLISHED'
                  AND (version.effective_from IS NULL OR version.effective_from<=now())
                  AND (version.effective_to IS NULL OR version.effective_to>now())
                ORDER BY (template.tenant_id IS NOT NULL) DESC,version.version_number DESC
                LIMIT 1
            """),
            {"tenant_id": tenant_id, "code": code},
        )
    ).one_or_none()
    if row is None:
        raise PermanentNotificationError("Published notification template is missing.")
    return TemplateVersion(*tuple(row))


async def _context(session: AsyncSession, tenant_id: UUID, identifier: UUID, prefix: str) -> None:
    await apply_transaction_context(
        session,
        RequestContext(
            tenant_id=tenant_id,
            user_id=None,
            external_subject=None,
            roles=frozenset(),
            support_group_ids=frozenset(),
            business_unit_id=None,
            correlation_id=str(identifier),
            request_id=f"{prefix}:{identifier}",
        ),
        rls_enabled=True,
    )
