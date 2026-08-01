\set ON_ERROR_STOP on

BEGIN;

-- Runtime roles are group roles only. Deployment creates login roles and
-- grants the appropriate group; credentials never belong in baseline SQL.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

REVOKE ALL ON SCHEMA util, identity, config, itsm, kb, ai, audit, integration FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA identity, config, itsm, kb, ai, audit, integration FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA identity, config, itsm, kb, ai, audit, integration FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA util, identity, config, itsm, kb, ai, audit, integration FROM PUBLIC;

GRANT USAGE ON SCHEMA util, identity, config, itsm, kb, ai, audit, integration
TO helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly;

GRANT SELECT ON ALL TABLES IN SCHEMA identity, config, itsm, kb, ai, audit, integration
TO helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA itsm, ai, audit, integration
TO helpdesk_app, helpdesk_worker;

GRANT INSERT, UPDATE ON
    itsm.ticket,
    itsm.ticket_participant,
    itsm.ticket_comment,
    itsm.ticket_attachment,
    itsm.ticket_custom_value,
    itsm.ticket_link,
    itsm.ticket_sla,
    itsm.ticket_approval,
    itsm.ticket_approver,
    itsm.ticket_communication,
    integration.idempotency_record
TO helpdesk_app;

GRANT INSERT ON
    itsm.assignment_history,
    itsm.ticket_event,
    itsm.ticket_sla_event,
    itsm.ticket_approval_decision,
    itsm.priority_override,
    audit.security_event,
    audit.audit_event,
    integration.outbox_event
TO helpdesk_app;

GRANT INSERT, UPDATE ON
    kb.ingestion_run,
    kb.ingestion_run_item,
    integration.idempotency_record,
    integration.notification_delivery,
    integration.email_message,
    integration.outbox_event,
    ai.conversation,
    ai.message,
    ai.agent_run,
    ai.feedback
TO helpdesk_worker;

GRANT INSERT ON
    ai.tool_call,
    ai.retrieval_evidence,
    ai.usage_ledger,
    audit.security_event,
    audit.audit_event
TO helpdesk_worker;

-- Explicit defense in depth for append-only history. The tables also reject
-- UPDATE and DELETE through triggers, including accidental owner mutations.
REVOKE UPDATE, DELETE ON
    itsm.assignment_history,
    itsm.ticket_event,
    itsm.ticket_sla_event,
    itsm.ticket_approval_decision,
    itsm.priority_override,
    ai.tool_call,
    ai.retrieval_evidence,
    ai.usage_ledger,
    audit.security_event,
    audit.audit_event
FROM helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly;

COMMIT;
