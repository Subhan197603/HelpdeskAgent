\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE config.routing_rule (
    routing_rule_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    project_id        uuid NOT NULL REFERENCES config.service_project(project_id),
    rule_name         varchar(200) NOT NULL,
    rule_priority     integer NOT NULL,
    condition_json    jsonb NOT NULL,
    assignment_group_id uuid NOT NULL REFERENCES identity.support_group(support_group_id),
    assignment_method varchar(40) NOT NULL DEFAULT 'GROUP_ONLY',
    assignee_user_id  uuid REFERENCES identity.app_user(user_id),
    active_flag       boolean NOT NULL DEFAULT true,
    effective_start_at timestamptz,
    effective_end_at  timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, rule_name),
    CONSTRAINT routing_rule_method_ck CHECK (
        assignment_method IN (
            'GROUP_ONLY','ROUND_ROBIN','LEAST_OPEN_TICKETS',
            'LEAST_WEIGHTED_WORKLOAD','SKILL_BASED','MANUAL','NAMED_ASSIGNEE'
        )
    )
);

CREATE TRIGGER routing_rule_set_updated_at
BEFORE UPDATE ON config.routing_rule
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

ALTER TABLE itsm.assignment_history
ADD CONSTRAINT assignment_history_routing_rule_fk
FOREIGN KEY (routing_rule_id) REFERENCES config.routing_rule(routing_rule_id);

CREATE TABLE config.queue_definition (
    queue_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    project_id        uuid NOT NULL REFERENCES config.service_project(project_id),
    queue_name        varchar(200) NOT NULL,
    description       text,
    filter_json       jsonb NOT NULL,
    sort_json         jsonb NOT NULL DEFAULT '[]'::jsonb,
    columns_json      jsonb NOT NULL DEFAULT '[]'::jsonb,
    visibility_type   varchar(30) NOT NULL DEFAULT 'PROJECT_AGENTS',
    owner_group_id    uuid REFERENCES identity.support_group(support_group_id),
    display_order     integer NOT NULL DEFAULT 0,
    active_flag       boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, queue_name),
    CONSTRAINT queue_visibility_ck CHECK (
        visibility_type IN ('PRIVATE','GROUP','PROJECT_AGENTS','ALL_AGENTS')
    )
);

CREATE TRIGGER queue_definition_set_updated_at
BEFORE UPDATE ON config.queue_definition
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE config.business_calendar (
    calendar_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    calendar_code     varchar(80) NOT NULL,
    calendar_name     varchar(200) NOT NULL,
    timezone_name     varchar(80) NOT NULL,
    twenty_four_seven_flag boolean NOT NULL DEFAULT false,
    active_flag       boolean NOT NULL DEFAULT true,
    UNIQUE (tenant_id, calendar_code)
);

CREATE TABLE config.calendar_working_period (
    working_period_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    calendar_id       uuid NOT NULL REFERENCES config.business_calendar(calendar_id) ON DELETE CASCADE,
    iso_day_of_week   smallint NOT NULL,
    start_local_time  time NOT NULL,
    end_local_time    time NOT NULL,
    CONSTRAINT calendar_day_ck CHECK (iso_day_of_week BETWEEN 1 AND 7),
    CONSTRAINT calendar_time_ck CHECK (start_local_time < end_local_time)
);

CREATE TABLE config.calendar_exception (
    exception_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    calendar_id       uuid NOT NULL REFERENCES config.business_calendar(calendar_id) ON DELETE CASCADE,
    exception_date    date NOT NULL,
    exception_type    varchar(20) NOT NULL,
    start_local_time  time,
    end_local_time    time,
    description       varchar(300),
    UNIQUE (calendar_id, exception_date),
    CONSTRAINT calendar_exception_type_ck CHECK (
        exception_type IN ('CLOSED','CUSTOM_HOURS')
    )
);

CREATE TABLE config.sla_definition (
    sla_definition_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    project_id        uuid NOT NULL REFERENCES config.service_project(project_id),
    sla_code          varchar(100) NOT NULL,
    sla_name          varchar(200) NOT NULL,
    metric_code       varchar(50) NOT NULL,
    description       text,
    start_condition_json jsonb NOT NULL,
    pause_condition_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    stop_condition_json jsonb NOT NULL,
    active_flag       boolean NOT NULL DEFAULT true,
    UNIQUE (project_id, sla_code),
    CONSTRAINT sla_metric_ck CHECK (
        metric_code IN (
            'TIME_TO_FIRST_RESPONSE','TIME_TO_RESOLUTION',
            'TIME_TO_NEXT_UPDATE','TIME_TO_APPROVAL','TIME_TO_FULFILMENT','CUSTOM'
        )
    )
);

CREATE TABLE config.sla_goal (
    sla_goal_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sla_definition_id uuid NOT NULL REFERENCES config.sla_definition(sla_definition_id) ON DELETE CASCADE,
    goal_name         varchar(200) NOT NULL,
    match_condition_json jsonb NOT NULL,
    target_minutes    integer NOT NULL,
    warning_minutes   integer,
    calendar_id       uuid NOT NULL REFERENCES config.business_calendar(calendar_id),
    priority_order    integer NOT NULL DEFAULT 100,
    active_flag       boolean NOT NULL DEFAULT true,
    CONSTRAINT sla_goal_target_ck CHECK (target_minutes > 0)
);

CREATE TABLE itsm.ticket_sla (
    ticket_sla_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    ticket_id         uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    sla_definition_id uuid NOT NULL REFERENCES config.sla_definition(sla_definition_id),
    sla_goal_id       uuid NOT NULL REFERENCES config.sla_goal(sla_goal_id),
    state_code        varchar(20) NOT NULL DEFAULT 'RUNNING',
    started_at        timestamptz NOT NULL,
    target_at         timestamptz NOT NULL,
    paused_at         timestamptz,
    accumulated_pause_seconds bigint NOT NULL DEFAULT 0,
    completed_at      timestamptz,
    breached_at       timestamptz,
    elapsed_working_seconds bigint NOT NULL DEFAULT 0,
    remaining_working_seconds bigint,
    last_calculated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ticket_id, sla_definition_id),
    CONSTRAINT ticket_sla_state_ck CHECK (
        state_code IN ('RUNNING','PAUSED','COMPLETED','BREACHED','CANCELLED')
    )
);

CREATE TABLE itsm.ticket_sla_event (
    ticket_sla_event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_sla_id     uuid NOT NULL REFERENCES itsm.ticket_sla(ticket_sla_id) ON DELETE CASCADE,
    event_type        varchar(30) NOT NULL,
    event_at          timestamptz NOT NULL DEFAULT now(),
    event_data_json   jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ticket_sla_event_type_ck CHECK (
        event_type IN ('STARTED','PAUSED','RESUMED','WARNING','BREACHED','COMPLETED','CANCELLED','RECALCULATED')
    )
);

CREATE TABLE config.approval_definition (
    approval_definition_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    project_id        uuid NOT NULL REFERENCES config.service_project(project_id),
    approval_code     varchar(100) NOT NULL,
    approval_name     varchar(200) NOT NULL,
    approval_mode     varchar(40) NOT NULL,
    minimum_count     integer,
    minimum_percentage numeric(5,2),
    approver_rule_json jsonb NOT NULL,
    on_approved_transition_id uuid REFERENCES config.workflow_transition(transition_id),
    on_rejected_transition_id uuid REFERENCES config.workflow_transition(transition_id),
    active_flag       boolean NOT NULL DEFAULT true,
    UNIQUE (project_id, approval_code),
    CONSTRAINT approval_mode_ck CHECK (
        approval_mode IN (
            'ANY_ONE_APPROVER','ALL_APPROVERS','MINIMUM_COUNT',
            'MINIMUM_PERCENTAGE','SEQUENTIAL_APPROVAL','GROUP_APPROVAL',
            'MANAGER_APPROVAL','CAB_APPROVAL'
        )
    )
);

CREATE TABLE itsm.ticket_approval (
    ticket_approval_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    ticket_id         uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    approval_definition_id uuid NOT NULL REFERENCES config.approval_definition(approval_definition_id),
    approval_status   varchar(20) NOT NULL DEFAULT 'PENDING',
    requested_at      timestamptz NOT NULL DEFAULT now(),
    completed_at      timestamptz,
    created_by        uuid REFERENCES identity.app_user(user_id),
    CONSTRAINT ticket_approval_status_ck CHECK (
        approval_status IN ('PENDING','APPROVED','REJECTED','CANCELLED','EXPIRED')
    )
);

CREATE TABLE itsm.ticket_approver (
    ticket_approval_id uuid NOT NULL REFERENCES itsm.ticket_approval(ticket_approval_id) ON DELETE CASCADE,
    approver_user_id  uuid NOT NULL REFERENCES identity.app_user(user_id),
    sequence_number   integer NOT NULL DEFAULT 1,
    decision_code     varchar(20),
    decision_comment  text,
    decided_at        timestamptz,
    delegated_from_user_id uuid REFERENCES identity.app_user(user_id),
    PRIMARY KEY (ticket_approval_id, approver_user_id),
    CONSTRAINT approver_decision_ck CHECK (
        decision_code IS NULL OR decision_code IN ('APPROVED','REJECTED','ABSTAINED')
    )
);

CREATE TABLE config.automation_rule (
    automation_rule_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    project_id        uuid REFERENCES config.service_project(project_id),
    rule_name         varchar(200) NOT NULL,
    trigger_code      varchar(50) NOT NULL,
    condition_json    jsonb NOT NULL DEFAULT '{}'::jsonb,
    action_json       jsonb NOT NULL,
    execution_order   integer NOT NULL DEFAULT 100,
    active_flag       boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER automation_rule_set_updated_at
BEFORE UPDATE ON config.automation_rule
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

COMMIT;
