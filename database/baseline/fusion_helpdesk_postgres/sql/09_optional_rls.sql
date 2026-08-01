\set ON_ERROR_STOP on

-- OPTIONAL: Apply only after the application sets these per transaction:
--   SET LOCAL app.tenant_id = '<tenant uuid>';
--   SET LOCAL app.user_id   = '<user uuid>';
-- Test thoroughly with a non-owner application database role.

BEGIN;

ALTER TABLE identity.business_unit ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity.app_user ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity.support_group ENABLE ROW LEVEL SECURITY;
ALTER TABLE config.service_project ENABLE ROW LEVEL SECURITY;
ALTER TABLE config.category ENABLE ROW LEVEL SECURITY;
ALTER TABLE config.request_type ENABLE ROW LEVEL SECURITY;
ALTER TABLE config.custom_field ENABLE ROW LEVEL SECURITY;
ALTER TABLE config.application_environment ENABLE ROW LEVEL SECURITY;
ALTER TABLE config.priority_matrix ENABLE ROW LEVEL SECURITY;
ALTER TABLE config.retention_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE itsm.ticket ENABLE ROW LEVEL SECURITY;
ALTER TABLE itsm.ticket_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE itsm.ticket_sla ENABLE ROW LEVEL SECURITY;
ALTER TABLE itsm.ticket_approval ENABLE ROW LEVEL SECURITY;
ALTER TABLE itsm.ticket_communication ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb.document ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.conversation ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.agent_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.feature_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.usage_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit.security_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit.audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit.legal_hold ENABLE ROW LEVEL SECURITY;
ALTER TABLE integration.idempotency_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE integration.notification_delivery ENABLE ROW LEVEL SECURITY;
ALTER TABLE integration.email_mailbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE integration.email_message ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_business_unit ON identity.business_unit
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_app_user ON identity.app_user
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_support_group ON identity.support_group
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_project ON config.service_project
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_category ON config.category
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_request_type ON config.request_type
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_custom_field ON config.custom_field
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_application_environment ON config.application_environment
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_or_global_priority_matrix ON config.priority_matrix
USING (tenant_id IS NULL OR tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id IS NULL OR tenant_id = util.current_tenant_id());

CREATE POLICY tenant_or_global_retention_policy ON config.retention_policy
USING (tenant_id IS NULL OR tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id IS NULL OR tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_ticket ON itsm.ticket
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_ticket_event ON itsm.ticket_event
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_ticket_sla ON itsm.ticket_sla
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_ticket_approval ON itsm.ticket_approval
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_ticket_communication ON itsm.ticket_communication
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_or_global_document ON kb.document
USING (tenant_id IS NULL OR tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id IS NULL OR tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_conversation ON ai.conversation
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_agent_run ON ai.agent_run
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_or_global_ai_feature_policy ON ai.feature_policy
USING (tenant_id IS NULL OR tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id IS NULL OR tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_ai_usage_ledger ON ai.usage_ledger
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_security_event ON audit.security_event
USING (tenant_id IS NULL OR tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id IS NULL OR tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_audit_event ON audit.audit_event
USING (tenant_id IS NULL OR tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id IS NULL OR tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_legal_hold ON audit.legal_hold
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_idempotency_record ON integration.idempotency_record
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_notification_delivery ON integration.notification_delivery
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_email_mailbox ON integration.email_mailbox
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

CREATE POLICY tenant_isolation_email_message ON integration.email_message
USING (tenant_id = util.current_tenant_id())
WITH CHECK (tenant_id = util.current_tenant_id());

COMMIT;
