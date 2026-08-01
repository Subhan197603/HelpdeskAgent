\set ON_ERROR_STOP on

BEGIN;

-- Section 8.6 configuration-versioning foundations. Existing configuration
-- tables remain stable aggregate identities; runtime rows reference immutable
-- domain-specific version rows rather than a generic version document.
ALTER TABLE config.workflow_version
    ADD COLUMN created_by uuid REFERENCES identity.app_user(user_id),
    ADD COLUMN approved_by uuid REFERENCES identity.app_user(user_id),
    ADD COLUMN approved_at timestamptz,
    ADD COLUMN change_reason text,
    ADD COLUMN previous_version_id uuid REFERENCES config.workflow_version(workflow_version_id),
    ADD COLUMN rollback_target_version_id uuid REFERENCES config.workflow_version(workflow_version_id),
    ADD COLUMN retired_at timestamptz,
    DROP CONSTRAINT workflow_version_status_ck,
    ADD CONSTRAINT workflow_version_status_ck CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    ADD CONSTRAINT workflow_version_effective_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    );

CREATE TRIGGER workflow_version_protect_published
BEFORE UPDATE OR DELETE ON config.workflow_version
FOR EACH ROW EXECUTE FUNCTION util.protect_published_configuration();

CREATE TABLE config.request_type_version (
    request_type_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_type_id uuid NOT NULL REFERENCES config.request_type(request_type_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    form_schema_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES config.request_type_version(request_type_version_id),
    rollback_target_version_id uuid REFERENCES config.request_type_version(request_type_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (request_type_id, version_number),
    UNIQUE (request_type_version_id, request_type_id),
    CONSTRAINT request_type_version_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    )
);

ALTER TABLE config.request_type_field
    DROP CONSTRAINT request_type_field_request_type_id_fkey,
    DROP CONSTRAINT request_type_field_pkey;
ALTER TABLE config.request_type_field
    RENAME COLUMN request_type_id TO request_type_version_id;
ALTER TABLE config.request_type_field
    ADD CONSTRAINT request_type_field_version_fk
        FOREIGN KEY (request_type_version_id)
        REFERENCES config.request_type_version(request_type_version_id),
    ADD PRIMARY KEY (request_type_version_id, custom_field_id);

CREATE TABLE config.routing_rule_version (
    routing_rule_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    routing_rule_id uuid NOT NULL REFERENCES config.routing_rule(routing_rule_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    rule_priority integer NOT NULL,
    condition_json jsonb NOT NULL,
    assignment_group_id uuid NOT NULL REFERENCES identity.support_group(support_group_id),
    assignment_method varchar(40) NOT NULL CHECK (
        assignment_method IN (
            'GROUP_ONLY', 'ROUND_ROBIN', 'LEAST_OPEN_TICKETS',
            'LEAST_WEIGHTED_WORKLOAD', 'SKILL_BASED', 'MANUAL', 'NAMED_ASSIGNEE'
        )
    ),
    assignee_user_id uuid REFERENCES identity.app_user(user_id),
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES config.routing_rule_version(routing_rule_version_id),
    rollback_target_version_id uuid REFERENCES config.routing_rule_version(routing_rule_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (routing_rule_id, version_number),
    UNIQUE (routing_rule_version_id, routing_rule_id),
    CONSTRAINT routing_rule_version_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    )
);

CREATE TABLE config.queue_definition_version (
    queue_definition_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    queue_id uuid NOT NULL REFERENCES config.queue_definition(queue_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    filter_json jsonb NOT NULL,
    sort_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    columns_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    visibility_type varchar(30) NOT NULL CHECK (
        visibility_type IN ('PRIVATE', 'GROUP', 'PROJECT_AGENTS', 'ALL_AGENTS')
    ),
    owner_group_id uuid REFERENCES identity.support_group(support_group_id),
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES config.queue_definition_version(queue_definition_version_id),
    rollback_target_version_id uuid REFERENCES config.queue_definition_version(queue_definition_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (queue_id, version_number),
    CONSTRAINT queue_version_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    )
);

CREATE TABLE config.business_calendar_version (
    business_calendar_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    calendar_id uuid NOT NULL REFERENCES config.business_calendar(calendar_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    timezone_name varchar(80) NOT NULL,
    twenty_four_seven_flag boolean NOT NULL DEFAULT false,
    schedule_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES config.business_calendar_version(business_calendar_version_id),
    rollback_target_version_id uuid REFERENCES config.business_calendar_version(business_calendar_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (calendar_id, version_number),
    CONSTRAINT calendar_version_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    )
);

ALTER TABLE config.calendar_working_period
    DROP CONSTRAINT calendar_working_period_calendar_id_fkey;
ALTER TABLE config.calendar_working_period
    RENAME COLUMN calendar_id TO business_calendar_version_id;
ALTER TABLE config.calendar_working_period
    ADD CONSTRAINT calendar_working_period_version_fk
        FOREIGN KEY (business_calendar_version_id)
        REFERENCES config.business_calendar_version(business_calendar_version_id) ON DELETE CASCADE,
    ADD UNIQUE (
        business_calendar_version_id, iso_day_of_week, start_local_time, end_local_time
    );

ALTER TABLE config.calendar_exception
    DROP CONSTRAINT calendar_exception_calendar_id_fkey,
    DROP CONSTRAINT calendar_exception_calendar_id_exception_date_key;
ALTER TABLE config.calendar_exception
    RENAME COLUMN calendar_id TO business_calendar_version_id;
ALTER TABLE config.calendar_exception
    ADD CONSTRAINT calendar_exception_version_fk
        FOREIGN KEY (business_calendar_version_id)
        REFERENCES config.business_calendar_version(business_calendar_version_id) ON DELETE CASCADE,
    ADD UNIQUE (business_calendar_version_id, exception_date);

CREATE TABLE config.sla_definition_version (
    sla_definition_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sla_definition_id uuid NOT NULL REFERENCES config.sla_definition(sla_definition_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    metric_code varchar(50) NOT NULL,
    start_condition_json jsonb NOT NULL,
    pause_condition_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    stop_condition_json jsonb NOT NULL,
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES config.sla_definition_version(sla_definition_version_id),
    rollback_target_version_id uuid REFERENCES config.sla_definition_version(sla_definition_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (sla_definition_id, version_number),
    CONSTRAINT sla_definition_version_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    )
);

CREATE TABLE config.sla_goal_version (
    sla_goal_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sla_goal_id uuid NOT NULL REFERENCES config.sla_goal(sla_goal_id),
    sla_definition_version_id uuid NOT NULL REFERENCES config.sla_definition_version(sla_definition_version_id),
    business_calendar_version_id uuid NOT NULL REFERENCES config.business_calendar_version(business_calendar_version_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    match_condition_json jsonb NOT NULL,
    target_minutes integer NOT NULL CHECK (target_minutes > 0),
    warning_minutes integer CHECK (warning_minutes IS NULL OR warning_minutes >= 0),
    priority_order integer NOT NULL DEFAULT 100,
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES config.sla_goal_version(sla_goal_version_id),
    rollback_target_version_id uuid REFERENCES config.sla_goal_version(sla_goal_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (sla_goal_id, version_number),
    UNIQUE (sla_goal_version_id, sla_goal_id, business_calendar_version_id),
    CONSTRAINT sla_goal_version_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    )
);

CREATE TABLE config.approval_definition_version (
    approval_definition_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_definition_id uuid NOT NULL REFERENCES config.approval_definition(approval_definition_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    approval_mode varchar(40) NOT NULL,
    minimum_count integer,
    minimum_percentage numeric(5,2),
    approver_rule_json jsonb NOT NULL,
    on_approved_transition_id uuid REFERENCES config.workflow_transition(transition_id),
    on_rejected_transition_id uuid REFERENCES config.workflow_transition(transition_id),
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES config.approval_definition_version(approval_definition_version_id),
    rollback_target_version_id uuid REFERENCES config.approval_definition_version(approval_definition_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (approval_definition_id, version_number),
    UNIQUE (approval_definition_version_id, approval_definition_id),
    CONSTRAINT approval_definition_version_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    )
);

CREATE TABLE config.notification_template (
    notification_template_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    template_code varchar(100) NOT NULL,
    template_name varchar(200) NOT NULL,
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, template_code)
);

CREATE TABLE config.notification_template_version (
    notification_template_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_template_id uuid NOT NULL REFERENCES config.notification_template(notification_template_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    channel_code varchar(30) NOT NULL REFERENCES config.channel(channel_code),
    subject_template text,
    body_template text NOT NULL,
    content_type varchar(40) NOT NULL DEFAULT 'TEXT' CHECK (
        content_type IN ('TEXT', 'HTML', 'MARKDOWN')
    ),
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES config.notification_template_version(notification_template_version_id),
    rollback_target_version_id uuid REFERENCES config.notification_template_version(notification_template_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (notification_template_id, version_number),
    CONSTRAINT notification_template_version_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    )
);

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'request_type_version', 'routing_rule_version', 'queue_definition_version',
        'business_calendar_version', 'sla_definition_version', 'sla_goal_version',
        'approval_definition_version', 'notification_template_version'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_protect_published BEFORE UPDATE OR DELETE ON config.%I '
            'FOR EACH ROW EXECUTE FUNCTION util.protect_published_configuration()',
            table_name, table_name
        );
    END LOOP;
END;
$$;

ALTER TABLE itsm.ticket
    ADD COLUMN request_type_version_id uuid NOT NULL REFERENCES config.request_type_version(request_type_version_id),
    ADD COLUMN application_environment_id uuid;

ALTER TABLE itsm.ticket
    DROP CONSTRAINT ticket_request_type_version_id_fkey,
    ADD CONSTRAINT ticket_request_type_version_fk
        FOREIGN KEY (request_type_version_id, request_type_id)
        REFERENCES config.request_type_version(request_type_version_id, request_type_id);

ALTER TABLE itsm.assignment_history
    ADD COLUMN routing_rule_version_id uuid REFERENCES config.routing_rule_version(routing_rule_version_id);

ALTER TABLE itsm.assignment_history
    DROP CONSTRAINT assignment_history_routing_rule_fk,
    DROP CONSTRAINT assignment_history_routing_rule_version_id_fkey,
    ADD CONSTRAINT assignment_history_routing_version_fk
        FOREIGN KEY (routing_rule_version_id, routing_rule_id)
        REFERENCES config.routing_rule_version(routing_rule_version_id, routing_rule_id)
        MATCH FULL;

ALTER TABLE itsm.ticket_sla
    ADD COLUMN sla_goal_version_id uuid NOT NULL REFERENCES config.sla_goal_version(sla_goal_version_id),
    ADD COLUMN business_calendar_version_id uuid NOT NULL REFERENCES config.business_calendar_version(business_calendar_version_id);

ALTER TABLE itsm.ticket_sla
    DROP CONSTRAINT ticket_sla_sla_goal_version_id_fkey,
    DROP CONSTRAINT ticket_sla_business_calendar_version_id_fkey,
    ADD CONSTRAINT ticket_sla_goal_calendar_version_fk
        FOREIGN KEY (sla_goal_version_id, sla_goal_id, business_calendar_version_id)
        REFERENCES config.sla_goal_version(
            sla_goal_version_id, sla_goal_id, business_calendar_version_id
        );

ALTER TABLE itsm.ticket_approval
    ADD COLUMN approval_definition_version_id uuid NOT NULL REFERENCES config.approval_definition_version(approval_definition_version_id);

ALTER TABLE itsm.ticket_approval
    DROP CONSTRAINT ticket_approval_approval_definition_version_id_fkey,
    ADD CONSTRAINT ticket_approval_definition_version_fk
        FOREIGN KEY (approval_definition_version_id, approval_definition_id)
        REFERENCES config.approval_definition_version(
            approval_definition_version_id, approval_definition_id
        );

CREATE TABLE integration.notification_delivery (
    notification_delivery_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    notification_template_version_id uuid NOT NULL REFERENCES config.notification_template_version(notification_template_version_id),
    resource_type varchar(100) NOT NULL,
    resource_id varchar(200) NOT NULL,
    recipient_reference varchar(320) NOT NULL,
    delivery_status varchar(20) NOT NULL DEFAULT 'PENDING' CHECK (
        delivery_status IN ('PENDING', 'SENDING', 'DELIVERED', 'FAILED', 'CANCELLED')
    ),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    provider_message_id varchar(300),
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz
);

-- Concurrency-safe idempotency storage. Request hashes are compared by the
-- application before replaying a durable response.
CREATE TABLE integration.idempotency_record (
    idempotency_record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    principal_type varchar(30) NOT NULL CHECK (
        principal_type IN ('USER', 'SERVICE', 'INTEGRATION', 'SYSTEM')
    ),
    principal_id varchar(300) NOT NULL,
    operation_code varchar(120) NOT NULL,
    idempotency_key varchar(255) NOT NULL,
    request_hash varchar(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    processing_status varchar(30) NOT NULL DEFAULT 'IN_PROGRESS' CHECK (
        processing_status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED_RETRYABLE', 'FAILED_FINAL', 'EXPIRED')
    ),
    lease_expires_at timestamptz,
    result_resource_type varchar(100),
    result_resource_id varchar(200),
    response_status integer CHECK (response_status IS NULL OR response_status BETWEEN 100 AND 599),
    response_payload_json jsonb,
    failure_code varchar(100),
    retryable_failure boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    expires_at timestamptz NOT NULL,
    UNIQUE (tenant_id, operation_code, idempotency_key),
    CONSTRAINT idempotency_expiry_ck CHECK (expires_at > created_at),
    CONSTRAINT idempotency_completion_ck CHECK (
        processing_status <> 'COMPLETED' OR completed_at IS NOT NULL
    )
);

CREATE INDEX idempotency_lease_ix
ON integration.idempotency_record (processing_status, lease_expires_at)
WHERE processing_status = 'IN_PROGRESS';

-- Operational application/environment/release registry. kb.release remains
-- the separate knowledge-document applicability registry.
CREATE TABLE config.application (
    application_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    application_code varchar(100) NOT NULL,
    application_name varchar(200) NOT NULL,
    release_family varchar(50) NOT NULL CHECK (
        release_family IN ('FUSION_APPLICATIONS', 'FUSION_DATA_INTELLIGENCE', 'ORACLE_ANALYTICS', 'OTHER')
    ),
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version integer NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE NULLS NOT DISTINCT (tenant_id, application_code),
    UNIQUE (application_id, release_family)
);

CREATE TABLE config.product_release (
    product_release_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id uuid NOT NULL,
    release_family varchar(50) NOT NULL,
    release_code varchar(40) NOT NULL,
    release_name varchar(150) NOT NULL,
    release_status varchar(20) NOT NULL DEFAULT 'PLANNED' CHECK (
        release_status IN ('PLANNED', 'CURRENT', 'SUPPORTED', 'SUPERSEDED', 'RETIRED')
    ),
    effective_from timestamptz,
    effective_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (release_family, release_code),
    UNIQUE (product_release_id, application_id),
    CONSTRAINT product_release_application_family_fk
        FOREIGN KEY (application_id, release_family)
        REFERENCES config.application(application_id, release_family),
    CONSTRAINT product_release_family_match_ck CHECK (
        (release_family = 'FUSION_APPLICATIONS' AND release_code !~ '[.]')
        OR (release_family = 'FUSION_DATA_INTELLIGENCE' AND release_code ~ '[.]')
        OR release_family NOT IN ('FUSION_APPLICATIONS', 'FUSION_DATA_INTELLIGENCE')
    ),
    CONSTRAINT product_release_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    )
);

CREATE TABLE config.application_environment (
    application_environment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    application_id uuid NOT NULL REFERENCES config.application(application_id),
    service_node_id uuid REFERENCES config.service_node(service_node_id),
    environment_code varchar(30) NOT NULL REFERENCES config.environment(environment_code),
    environment_name varchar(150) NOT NULL,
    instance_identifier varchar(200) NOT NULL,
    region_code varchar(100),
    current_product_release_id uuid REFERENCES config.product_release(product_release_id),
    planned_product_release_id uuid REFERENCES config.product_release(product_release_id),
    release_effective_at timestamptz,
    maintenance_window text,
    business_owner_user_id uuid REFERENCES identity.app_user(user_id),
    technical_owner_user_id uuid REFERENCES identity.app_user(user_id),
    primary_support_group_id uuid REFERENCES identity.support_group(support_group_id),
    criticality_code varchar(20) CHECK (
        criticality_code IS NULL OR criticality_code IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')
    ),
    recovery_tier varchar(30),
    data_classification varchar(30) NOT NULL DEFAULT 'INTERNAL' CHECK (
        data_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')
    ),
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version integer NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE (tenant_id, application_id, instance_identifier)
);

ALTER TABLE itsm.ticket
    ADD CONSTRAINT ticket_application_environment_fk
    FOREIGN KEY (application_environment_id)
    REFERENCES config.application_environment(application_environment_id);

CREATE TABLE config.environment_release_assignment (
    environment_release_assignment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_environment_id uuid NOT NULL REFERENCES config.application_environment(application_environment_id),
    product_release_id uuid NOT NULL REFERENCES config.product_release(product_release_id),
    assignment_type varchar(20) NOT NULL CHECK (assignment_type IN ('CURRENT', 'PLANNED', 'HISTORICAL')),
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    assigned_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT environment_release_assignment_dates_ck CHECK (
        effective_to IS NULL OR effective_to > effective_from
    )
);

CREATE UNIQUE INDEX environment_one_current_release_ux
ON config.environment_release_assignment (application_environment_id)
WHERE assignment_type = 'CURRENT' AND effective_to IS NULL;

CREATE TABLE config.diagnostic_endpoint (
    diagnostic_endpoint_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    application_environment_id uuid NOT NULL REFERENCES config.application_environment(application_environment_id),
    endpoint_code varchar(100) NOT NULL,
    endpoint_uri text NOT NULL,
    endpoint_type varchar(40) NOT NULL,
    approval_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        approval_status IN ('DRAFT', 'APPROVED', 'RETIRED')
    ),
    credential_secret_reference text,
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (application_environment_id, endpoint_code),
    CONSTRAINT diagnostic_endpoint_secret_ck CHECK (
        credential_secret_reference IS NULL OR credential_secret_reference !~* '(password|api[_-]?key|secret)='
    )
);

-- Deterministic impact/urgency matrix. Nullable scope columns allow ordered
-- project/service/tenant overrides without copying the global definitions.
CREATE TABLE config.impact (
    impact_code varchar(20) PRIMARY KEY,
    impact_name varchar(100) NOT NULL,
    rank_order integer NOT NULL UNIQUE CHECK (rank_order > 0),
    active_flag boolean NOT NULL DEFAULT true
);

CREATE TABLE config.urgency (
    urgency_code varchar(20) PRIMARY KEY,
    urgency_name varchar(100) NOT NULL,
    rank_order integer NOT NULL UNIQUE CHECK (rank_order > 0),
    active_flag boolean NOT NULL DEFAULT true
);

CREATE TABLE config.priority_matrix (
    priority_matrix_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    project_id uuid REFERENCES config.service_project(project_id),
    service_node_id uuid REFERENCES config.service_node(service_node_id),
    impact_code varchar(20) NOT NULL REFERENCES config.impact(impact_code),
    urgency_code varchar(20) NOT NULL REFERENCES config.urgency(urgency_code),
    priority_code varchar(20) NOT NULL REFERENCES config.priority(priority_code),
    evaluation_order integer NOT NULL DEFAULT 100 CHECK (evaluation_order > 0),
    effective_from timestamptz NOT NULL DEFAULT '-infinity',
    effective_to timestamptz,
    approval_status varchar(20) NOT NULL DEFAULT 'APPROVED' CHECK (
        approval_status IN ('DRAFT', 'UNDER_REVIEW', 'APPROVED', 'RETIRED')
    ),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (
        tenant_id, project_id, service_node_id, impact_code, urgency_code, effective_from
    ),
    CONSTRAINT priority_matrix_scope_ck CHECK (
        project_id IS NULL OR tenant_id IS NOT NULL
    ),
    CONSTRAINT priority_matrix_dates_ck CHECK (
        effective_to IS NULL OR effective_to > effective_from
    )
);

ALTER TABLE itsm.ticket
    ADD CONSTRAINT ticket_impact_fk FOREIGN KEY (impact_code) REFERENCES config.impact(impact_code),
    ADD CONSTRAINT ticket_urgency_fk FOREIGN KEY (urgency_code) REFERENCES config.urgency(urgency_code);

CREATE TABLE itsm.priority_override (
    priority_override_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id uuid NOT NULL REFERENCES itsm.ticket(ticket_id),
    previous_priority_code varchar(20) NOT NULL REFERENCES config.priority(priority_code),
    override_priority_code varchar(20) NOT NULL REFERENCES config.priority(priority_code),
    override_reason text NOT NULL,
    authorized_by uuid NOT NULL REFERENCES identity.app_user(user_id),
    correlation_id uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Email gateway tables store normalized correlation metadata and protected
-- object references only; raw MIME and attachment bytes remain object-storage data.
CREATE TABLE integration.email_mailbox (
    email_mailbox_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    provider_code varchar(50) NOT NULL,
    mailbox_identifier varchar(320) NOT NULL,
    channel_code varchar(30) NOT NULL DEFAULT 'EMAIL' REFERENCES config.channel(channel_code),
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, provider_code, mailbox_identifier)
);

CREATE TABLE itsm.ticket_communication (
    ticket_communication_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    ticket_id uuid NOT NULL REFERENCES itsm.ticket(ticket_id),
    comment_id uuid REFERENCES itsm.ticket_comment(comment_id),
    direction_code varchar(20) NOT NULL CHECK (direction_code IN ('INBOUND', 'OUTBOUND', 'INTERNAL')),
    channel_code varchar(30) NOT NULL REFERENCES config.channel(channel_code),
    external_reference varchar(500),
    subject text,
    occurred_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE integration.email_message (
    email_message_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    email_mailbox_id uuid NOT NULL REFERENCES integration.email_mailbox(email_mailbox_id),
    ticket_communication_id uuid REFERENCES itsm.ticket_communication(ticket_communication_id),
    ticket_id uuid REFERENCES itsm.ticket(ticket_id),
    provider_message_id varchar(500),
    rfc_message_id varchar(998),
    provider_thread_id varchar(500),
    in_reply_to varchar(998),
    references_header text,
    sender_address varchar(320) NOT NULL,
    reply_to_address varchar(320),
    subject text,
    received_or_sent_at timestamptz NOT NULL,
    processing_status varchar(30) NOT NULL DEFAULT 'RECEIVED' CHECK (
        processing_status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED_RETRYABLE', 'FAILED_FINAL', 'IGNORED')
    ),
    retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    processing_error text,
    original_message_object_uri text NOT NULL,
    message_sha256 varchar(64) NOT NULL CHECK (message_sha256 ~ '^[0-9a-f]{64}$'),
    sanitized_headers_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX email_message_provider_id_ux
ON integration.email_message (tenant_id, email_mailbox_id, provider_message_id)
WHERE provider_message_id IS NOT NULL;

CREATE UNIQUE INDEX email_message_rfc_id_ux
ON integration.email_message (tenant_id, email_mailbox_id, rfc_message_id)
WHERE rfc_message_id IS NOT NULL;

CREATE TABLE integration.email_recipient (
    email_message_id uuid NOT NULL REFERENCES integration.email_message(email_message_id) ON DELETE CASCADE,
    recipient_type varchar(10) NOT NULL CHECK (recipient_type IN ('TO', 'CC', 'BCC')),
    recipient_address varchar(320) NOT NULL,
    display_name varchar(250),
    PRIMARY KEY (email_message_id, recipient_type, recipient_address)
);

-- Retention policy and legal hold are modeled separately so a hold can cover
-- multiple resources without mutable legal-hold flags on every domain table.
CREATE TABLE config.retention_policy (
    retention_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    project_id uuid REFERENCES config.service_project(project_id),
    policy_code varchar(100) NOT NULL,
    policy_name varchar(200) NOT NULL,
    record_category varchar(60) NOT NULL CHECK (
        record_category IN (
            'TICKET', 'COMMENT', 'ATTACHMENT', 'AI_CONVERSATION', 'AI_MESSAGE',
            'AI_RUN', 'AI_TOOL_CALL', 'AI_EVIDENCE', 'KNOWLEDGE_DOCUMENT',
            'KNOWLEDGE_VERSION', 'AUDIT_EVENT', 'INTEGRATION_MESSAGE',
            'REPORTING_DATA', 'EMAIL_MESSAGE', 'ARCHIVED_EXPORT', 'BACKUP'
        )
    ),
    security_classification varchar(30),
    jurisdiction_code varchar(30),
    retention_days integer NOT NULL CHECK (retention_days >= 0),
    archive_days integer CHECK (archive_days IS NULL OR archive_days >= 0),
    final_action varchar(20) NOT NULL CHECK (final_action IN ('DELETE', 'ANONYMIZE', 'ARCHIVE', 'RETAIN')),
    legal_hold_behavior varchar(30) NOT NULL DEFAULT 'SUSPEND_ACTION' CHECK (
        legal_hold_behavior IN ('SUSPEND_ACTION', 'RETAIN_COPY')
    ),
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    approval_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        approval_status IN ('DRAFT', 'UNDER_REVIEW', 'APPROVED', 'RETIRED')
    ),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    review_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version integer NOT NULL DEFAULT 1 CHECK (row_version > 0),
    UNIQUE NULLS NOT DISTINCT (tenant_id, project_id, policy_code),
    CONSTRAINT retention_policy_dates_ck CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE TABLE config.retention_policy_assignment (
    retention_policy_assignment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    retention_policy_id uuid NOT NULL REFERENCES config.retention_policy(retention_policy_id),
    resource_type varchar(100) NOT NULL,
    resource_id varchar(200),
    assigned_at timestamptz NOT NULL DEFAULT now(),
    assigned_by uuid REFERENCES identity.app_user(user_id),
    UNIQUE NULLS NOT DISTINCT (retention_policy_id, resource_type, resource_id)
);

CREATE TABLE audit.legal_hold (
    legal_hold_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    hold_code varchar(100) NOT NULL,
    hold_name varchar(250) NOT NULL,
    hold_reason text NOT NULL,
    hold_status varchar(20) NOT NULL DEFAULT 'ACTIVE' CHECK (
        hold_status IN ('ACTIVE', 'RELEASED', 'EXPIRED')
    ),
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    authorized_by uuid NOT NULL REFERENCES identity.app_user(user_id),
    released_by uuid REFERENCES identity.app_user(user_id),
    released_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, hold_code),
    CONSTRAINT legal_hold_dates_ck CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE TABLE audit.legal_hold_resource (
    legal_hold_resource_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_hold_id uuid NOT NULL REFERENCES audit.legal_hold(legal_hold_id),
    resource_type varchar(100) NOT NULL,
    resource_id varchar(200) NOT NULL,
    storage_location varchar(40) NOT NULL CHECK (
        storage_location IN ('POSTGRESQL', 'OBJECT_STORAGE', 'SEARCH_INDEX', 'REPORTING', 'PROVIDER', 'BACKUP')
    ),
    assigned_at timestamptz NOT NULL DEFAULT now(),
    assigned_by uuid NOT NULL REFERENCES identity.app_user(user_id),
    UNIQUE (legal_hold_id, resource_type, resource_id, storage_location)
);

-- Expand attachment metadata to cover quarantine, malware scanning, release,
-- classification, retention, and deletion without storing file bytes or keys.
ALTER TABLE itsm.ticket_attachment
    RENAME COLUMN object_uri TO quarantine_object_uri;
ALTER TABLE itsm.ticket_attachment
    RENAME COLUMN content_type TO client_declared_content_type;
ALTER TABLE itsm.ticket_attachment
    ADD COLUMN protected_object_uri text,
    ADD COLUMN detected_mime_type varchar(200),
    ADD COLUMN malware_scanned_at timestamptz,
    ADD COLUMN scanner_engine varchar(100),
    ADD COLUMN scanner_version varchar(100),
    ADD COLUMN threat_name text,
    ADD COLUMN scan_error_details text,
    ADD COLUMN quarantine_status varchar(30) NOT NULL DEFAULT 'QUARANTINED' CHECK (
        quarantine_status IN ('QUARANTINED', 'SCANNING', 'RELEASED', 'REJECTED', 'DELETED')
    ),
    ADD COLUMN quarantined_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN released_at timestamptz,
    ADD COLUMN rejected_at timestamptz,
    ADD COLUMN encryption_status varchar(30) NOT NULL DEFAULT 'PROVIDER_MANAGED' CHECK (
        encryption_status IN ('PROVIDER_MANAGED', 'CUSTOMER_MANAGED', 'NOT_APPLICABLE')
    ),
    ADD COLUMN retention_policy_id uuid REFERENCES config.retention_policy(retention_policy_id),
    ADD COLUMN deleted_at timestamptz,
    ADD COLUMN visibility_code varchar(30) NOT NULL DEFAULT 'INTERNAL' CHECK (
        visibility_code IN ('PUBLIC', 'INTERNAL', 'RESTRICTED')
    ),
    ALTER COLUMN file_size_bytes SET NOT NULL,
    ADD CONSTRAINT attachment_file_size_ck CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
    ADD CONSTRAINT attachment_checksum_ck CHECK (sha256_checksum ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT attachment_security_classification_ck CHECK (
        security_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')
    ),
    ADD CONSTRAINT attachment_release_ck CHECK (
        quarantine_status <> 'RELEASED' OR (
            malware_scan_status = 'CLEAN' AND protected_object_uri IS NOT NULL AND released_at IS NOT NULL
        )
    );

-- Provider-independent, versioned AI configuration. These tables store model
-- aliases and secret-manager references are deliberately absent.
CREATE TABLE kb.embedding_configuration (
    embedding_configuration_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    embedding_code varchar(100) NOT NULL,
    embedding_name varchar(200) NOT NULL,
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, embedding_code)
);

CREATE TABLE kb.embedding_configuration_version (
    embedding_configuration_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    embedding_configuration_id uuid NOT NULL REFERENCES kb.embedding_configuration(embedding_configuration_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    embedding_model_code varchar(100) NOT NULL REFERENCES kb.embedding_model(embedding_model_code),
    chunking_configuration_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES kb.embedding_configuration_version(embedding_configuration_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (embedding_configuration_id, version_number)
);

CREATE TRIGGER embedding_configuration_version_protect_published
BEFORE UPDATE OR DELETE ON kb.embedding_configuration_version
FOR EACH ROW EXECUTE FUNCTION util.protect_published_configuration();

CREATE TABLE ai.prompt_template (
    prompt_template_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    prompt_code varchar(100) NOT NULL,
    prompt_name varchar(200) NOT NULL,
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, prompt_code)
);

CREATE TABLE ai.prompt_version (
    prompt_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_template_id uuid NOT NULL REFERENCES ai.prompt_template(prompt_template_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    prompt_text text NOT NULL,
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES ai.prompt_version(prompt_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (prompt_template_id, version_number)
);

CREATE TABLE ai.tool_set (
    tool_set_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    tool_set_code varchar(100) NOT NULL,
    tool_set_name varchar(200) NOT NULL,
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, tool_set_code)
);

CREATE TABLE ai.tool_set_version (
    tool_set_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_set_id uuid NOT NULL REFERENCES ai.tool_set(tool_set_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    tool_definitions_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES ai.tool_set_version(tool_set_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (tool_set_id, version_number)
);

CREATE TABLE ai.retrieval_configuration (
    retrieval_configuration_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    retrieval_code varchar(100) NOT NULL,
    retrieval_name varchar(200) NOT NULL,
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, retrieval_code)
);

CREATE TABLE ai.retrieval_configuration_version (
    retrieval_configuration_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    retrieval_configuration_id uuid NOT NULL REFERENCES ai.retrieval_configuration(retrieval_configuration_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    configuration_json jsonb NOT NULL,
    embedding_configuration_version_id uuid
        REFERENCES kb.embedding_configuration_version(embedding_configuration_version_id),
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES ai.retrieval_configuration_version(retrieval_configuration_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (retrieval_configuration_id, version_number)
);

CREATE TABLE ai.model_policy (
    model_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    policy_code varchar(100) NOT NULL,
    policy_name varchar(200) NOT NULL,
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, policy_code)
);

CREATE TABLE ai.model_policy_version (
    model_policy_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_policy_id uuid NOT NULL REFERENCES ai.model_policy(model_policy_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    provider_alias varchar(100) NOT NULL,
    model_alias varchar(200) NOT NULL,
    fallback_provider_alias varchar(100),
    fallback_model_alias varchar(200),
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES ai.model_policy_version(model_policy_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (model_policy_id, version_number)
);

CREATE TABLE ai.agent_configuration (
    agent_configuration_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    agent_code varchar(100) NOT NULL,
    agent_name varchar(200) NOT NULL,
    active_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, agent_code)
);

CREATE TABLE ai.agent_configuration_version (
    agent_configuration_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_configuration_id uuid NOT NULL REFERENCES ai.agent_configuration(agent_configuration_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    version_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        version_status IN ('DRAFT', 'UNDER_REVIEW', 'PUBLISHED', 'RETIRED')
    ),
    prompt_version_id uuid NOT NULL REFERENCES ai.prompt_version(prompt_version_id),
    tool_set_version_id uuid NOT NULL REFERENCES ai.tool_set_version(tool_set_version_id),
    retrieval_configuration_version_id uuid NOT NULL REFERENCES ai.retrieval_configuration_version(retrieval_configuration_version_id),
    model_policy_version_id uuid NOT NULL REFERENCES ai.model_policy_version(model_policy_version_id),
    effective_from timestamptz,
    effective_to timestamptz,
    created_by uuid REFERENCES identity.app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    change_reason text,
    previous_version_id uuid REFERENCES ai.agent_configuration_version(agent_configuration_version_id),
    published_at timestamptz,
    retired_at timestamptz,
    UNIQUE (agent_configuration_id, version_number)
);

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'prompt_version', 'tool_set_version', 'retrieval_configuration_version',
        'model_policy_version', 'agent_configuration_version'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_protect_published BEFORE UPDATE OR DELETE ON ai.%I '
            'FOR EACH ROW EXECUTE FUNCTION util.protect_published_configuration()',
            table_name, table_name
        );
    END LOOP;
END;
$$;

CREATE TABLE ai.feature_policy (
    feature_policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    application_environment_id uuid REFERENCES config.application_environment(application_environment_id),
    agent_configuration_id uuid REFERENCES ai.agent_configuration(agent_configuration_id),
    use_case_code varchar(100),
    scope_type varchar(20) NOT NULL CHECK (
        scope_type IN ('GLOBAL', 'TENANT', 'ENVIRONMENT', 'AGENT', 'USE_CASE')
    ),
    enabled_flag boolean NOT NULL DEFAULT false,
    daily_budget numeric(18,4) CHECK (daily_budget IS NULL OR daily_budget >= 0),
    monthly_budget numeric(18,4) CHECK (monthly_budget IS NULL OR monthly_budget >= 0),
    budget_currency char(3),
    warning_threshold_percent numeric(5,2) CHECK (
        warning_threshold_percent IS NULL OR warning_threshold_percent BETWEEN 0 AND 100
    ),
    hard_stop_threshold_percent numeric(5,2) CHECK (
        hard_stop_threshold_percent IS NULL OR hard_stop_threshold_percent BETWEEN 0 AND 100
    ),
    maximum_input_tokens integer CHECK (maximum_input_tokens IS NULL OR maximum_input_tokens > 0),
    maximum_output_tokens integer CHECK (maximum_output_tokens IS NULL OR maximum_output_tokens > 0),
    maximum_context_tokens integer CHECK (maximum_context_tokens IS NULL OR maximum_context_tokens > 0),
    maximum_tool_calls integer CHECK (maximum_tool_calls IS NULL OR maximum_tool_calls >= 0),
    maximum_retrieved_chunks integer CHECK (maximum_retrieved_chunks IS NULL OR maximum_retrieved_chunks >= 0),
    per_user_requests_per_minute integer CHECK (
        per_user_requests_per_minute IS NULL OR per_user_requests_per_minute > 0
    ),
    approval_status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (
        approval_status IN ('DRAFT', 'UNDER_REVIEW', 'APPROVED', 'RETIRED')
    ),
    effective_from timestamptz,
    effective_to timestamptz,
    approved_by uuid REFERENCES identity.app_user(user_id),
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version integer NOT NULL DEFAULT 1 CHECK (row_version > 0),
    CONSTRAINT ai_feature_policy_scope_ck CHECK (
        (scope_type = 'GLOBAL' AND tenant_id IS NULL AND application_environment_id IS NULL AND agent_configuration_id IS NULL AND use_case_code IS NULL)
        OR (scope_type = 'TENANT' AND tenant_id IS NOT NULL AND application_environment_id IS NULL AND agent_configuration_id IS NULL AND use_case_code IS NULL)
        OR (scope_type = 'ENVIRONMENT' AND application_environment_id IS NOT NULL)
        OR (scope_type = 'AGENT' AND agent_configuration_id IS NOT NULL)
        OR (scope_type = 'USE_CASE' AND use_case_code IS NOT NULL)
    ),
    CONSTRAINT ai_feature_policy_dates_ck CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from
    ),
    CONSTRAINT ai_feature_policy_budget_currency_ck CHECK (
        (daily_budget IS NULL AND monthly_budget IS NULL) OR budget_currency IS NOT NULL
    )
);

CREATE UNIQUE INDEX ai_one_global_policy_ux
ON ai.feature_policy (scope_type)
WHERE scope_type = 'GLOBAL';

ALTER TABLE ai.agent_run
    ADD COLUMN agent_configuration_version_id uuid REFERENCES ai.agent_configuration_version(agent_configuration_version_id),
    ADD COLUMN prompt_version_id uuid REFERENCES ai.prompt_version(prompt_version_id),
    ADD COLUMN tool_set_version_id uuid REFERENCES ai.tool_set_version(tool_set_version_id),
    ADD COLUMN model_policy_version_id uuid REFERENCES ai.model_policy_version(model_policy_version_id),
    ADD COLUMN retrieval_configuration_version_id uuid REFERENCES ai.retrieval_configuration_version(retrieval_configuration_version_id),
    ADD COLUMN feature_policy_id uuid REFERENCES ai.feature_policy(feature_policy_id);

CREATE TABLE ai.usage_ledger (
    usage_ledger_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    agent_run_id uuid REFERENCES ai.agent_run(agent_run_id),
    agent_configuration_id uuid REFERENCES ai.agent_configuration(agent_configuration_id),
    application_environment_id uuid REFERENCES config.application_environment(application_environment_id),
    user_id uuid REFERENCES identity.app_user(user_id),
    provider_alias varchar(100) NOT NULL,
    model_alias varchar(200) NOT NULL,
    use_case_code varchar(100) NOT NULL,
    input_tokens integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cached_tokens integer NOT NULL DEFAULT 0 CHECK (cached_tokens >= 0),
    tool_call_count integer NOT NULL DEFAULT 0 CHECK (tool_call_count >= 0),
    estimated_cost numeric(18,8) NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0),
    currency_code char(3) NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ai_usage_ledger_budget_ix
ON ai.usage_ledger (tenant_id, occurred_at DESC, agent_configuration_id);

-- General append-only audit store; security_event remains the focused security stream.
CREATE TABLE audit.audit_event (
    audit_event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid REFERENCES identity.tenant(tenant_id),
    actor_id varchar(300),
    actor_type varchar(30) NOT NULL CHECK (
        actor_type IN ('USER', 'AGENT', 'SYSTEM', 'INTEGRATION', 'AI', 'ANONYMOUS')
    ),
    action_code varchar(120) NOT NULL,
    resource_type varchar(100) NOT NULL,
    resource_id varchar(200),
    previous_values_json jsonb,
    new_values_json jsonb,
    change_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    reason text,
    correlation_id uuid,
    request_id varchar(200),
    trace_id varchar(100),
    source_channel varchar(30),
    source_ip inet,
    user_agent text,
    outcome_code varchar(20) NOT NULL CHECK (outcome_code IN ('SUCCESS', 'DENIED', 'FAILED', 'PARTIAL')),
    failure_reason text,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_event_resource_time_ix
ON audit.audit_event (tenant_id, resource_type, resource_id, occurred_at DESC, audit_event_id);

-- Immutable approval decisions are separate from mutable approver assignments.
CREATE TABLE itsm.ticket_approval_decision (
    ticket_approval_decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    ticket_approval_id uuid NOT NULL REFERENCES itsm.ticket_approval(ticket_approval_id),
    approver_user_id uuid NOT NULL REFERENCES identity.app_user(user_id),
    decision_code varchar(20) NOT NULL CHECK (
        decision_code IN ('APPROVED', 'REJECTED', 'ABSTAINED', 'DELEGATED')
    ),
    decision_comment text,
    delegated_to_user_id uuid REFERENCES identity.app_user(user_id),
    correlation_id uuid,
    decided_at timestamptz NOT NULL DEFAULT now()
);

DO $$
DECLARE
    target_table text;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        'itsm.ticket_event',
        'itsm.ticket_sla_event',
        'itsm.ticket_approval_decision',
        'itsm.priority_override',
        'ai.retrieval_evidence',
        'ai.usage_ledger',
        'audit.security_event',
        'audit.audit_event'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER immutable_%s BEFORE UPDATE OR DELETE ON %s '
            'FOR EACH ROW EXECUTE FUNCTION util.reject_immutable_mutation()',
            replace(target_table, '.', '_'), target_table
        );
    END LOOP;
END;
$$;

-- Extend the existing service tree; do not introduce a second hierarchy.
ALTER TABLE config.service_node
    DROP CONSTRAINT service_node_type_ck,
    ADD CONSTRAINT service_node_type_ck CHECK (
        node_type IN (
            'SERVICE_FAMILY', 'BUSINESS_SERVICE', 'TECHNICAL_SERVICE', 'SERVICE',
            'APPLICATION', 'MODULE', 'BUSINESS_PROCESS', 'COMPONENT'
        )
    ),
    ADD COLUMN criticality_code varchar(20) CHECK (
        criticality_code IS NULL OR criticality_code IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')
    ),
    ADD COLUMN support_calendar_id uuid REFERENCES config.business_calendar(calendar_id),
    ADD COLUMN recovery_tier varchar(30),
    ADD COLUMN data_classification varchar(30) NOT NULL DEFAULT 'INTERNAL' CHECK (
        data_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')
    ),
    ADD COLUMN vendor_reference varchar(250),
    ADD COLUMN row_version integer NOT NULL DEFAULT 1 CHECK (row_version > 0);

CREATE TABLE config.service_node_ownership (
    service_node_ownership_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service_node_id uuid NOT NULL REFERENCES config.service_node(service_node_id),
    ownership_role varchar(40) NOT NULL CHECK (
        ownership_role IN (
            'BUSINESS_OWNER', 'TECHNICAL_OWNER', 'SERVICE_OWNER', 'SUPPORT_MANAGER',
            'PRIMARY_SUPPORT_GROUP', 'ESCALATION_GROUP', 'VENDOR_OWNER', 'VENDOR_CONTACT'
        )
    ),
    user_id uuid REFERENCES identity.app_user(user_id),
    support_group_id uuid REFERENCES identity.support_group(support_group_id),
    external_reference varchar(300),
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid REFERENCES identity.app_user(user_id),
    CONSTRAINT service_ownership_principal_ck CHECK (
        num_nonnulls(user_id, support_group_id, external_reference) = 1
    ),
    CONSTRAINT service_ownership_dates_ck CHECK (
        effective_to IS NULL OR effective_to > effective_from
    )
);

CREATE INDEX service_node_ownership_active_ix
ON config.service_node_ownership (service_node_id, ownership_role, effective_from, effective_to);

COMMIT;
