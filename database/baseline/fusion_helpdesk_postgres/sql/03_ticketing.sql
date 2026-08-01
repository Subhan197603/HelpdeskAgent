\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE itsm.project_ticket_counter (
    project_id       uuid PRIMARY KEY REFERENCES config.service_project(project_id),
    next_ticket_number bigint NOT NULL DEFAULT 1,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION itsm.initialize_project_counter()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO itsm.project_ticket_counter(project_id, next_ticket_number)
    VALUES (NEW.project_id, 1)
    ON CONFLICT (project_id) DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE TRIGGER project_counter_after_insert
AFTER INSERT ON config.service_project
FOR EACH ROW EXECUTE FUNCTION itsm.initialize_project_counter();

INSERT INTO itsm.project_ticket_counter(project_id, next_ticket_number)
SELECT project_id, 1 FROM config.service_project
ON CONFLICT (project_id) DO NOTHING;

CREATE TABLE itsm.ticket (
    ticket_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    project_id        uuid NOT NULL REFERENCES config.service_project(project_id),
    ticket_number     bigint,
    ticket_key        varchar(40),

    request_type_id   uuid NOT NULL REFERENCES config.request_type(request_type_id),
    work_type_id      uuid NOT NULL REFERENCES config.work_type(work_type_id),
    workflow_version_id uuid NOT NULL REFERENCES config.workflow_version(workflow_version_id),
    status_id         uuid NOT NULL REFERENCES config.workflow_status(status_id),

    summary           varchar(500) NOT NULL,
    description       text,

    reporter_user_id  uuid NOT NULL REFERENCES identity.app_user(user_id),
    requested_for_user_id uuid REFERENCES identity.app_user(user_id),
    business_unit_id  uuid REFERENCES identity.business_unit(business_unit_id),

    service_node_id   uuid REFERENCES config.service_node(service_node_id),
    category_id       uuid REFERENCES config.category(category_id),

    impact_code       varchar(20),
    urgency_code      varchar(20),
    priority_code     varchar(20) NOT NULL REFERENCES config.priority(priority_code),

    assignment_group_id uuid REFERENCES identity.support_group(support_group_id),
    assignee_user_id  uuid REFERENCES identity.app_user(user_id),

    channel_code      varchar(30) NOT NULL REFERENCES config.channel(channel_code),
    environment_code  varchar(30) REFERENCES config.environment(environment_code),

    resolution_code   varchar(50) REFERENCES config.resolution_code(resolution_code),
    resolution_summary text,

    first_response_at timestamptz,
    resolved_at       timestamptz,
    closed_at         timestamptz,

    ai_created_flag   boolean NOT NULL DEFAULT false,
    ai_classification_score numeric(6,5),
    source_conversation_id uuid,

    created_at        timestamptz NOT NULL DEFAULT now(),
    created_by        uuid NOT NULL REFERENCES identity.app_user(user_id),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    updated_by        uuid NOT NULL REFERENCES identity.app_user(user_id),
    row_version       integer NOT NULL DEFAULT 1,

    UNIQUE (tenant_id, ticket_key),
    UNIQUE (project_id, ticket_number),
    CONSTRAINT ticket_ai_score_ck CHECK (
        ai_classification_score IS NULL OR
        ai_classification_score BETWEEN 0 AND 1
    )
);

CREATE OR REPLACE FUNCTION itsm.assign_ticket_key()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_number bigint;
    v_project_key varchar(12);
BEGIN
    IF NEW.ticket_number IS NULL THEN
        UPDATE itsm.project_ticket_counter
           SET next_ticket_number = next_ticket_number + 1,
               updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id
         RETURNING next_ticket_number - 1 INTO v_number;

        IF v_number IS NULL THEN
            INSERT INTO itsm.project_ticket_counter(project_id, next_ticket_number)
            VALUES (NEW.project_id, 2)
            ON CONFLICT (project_id)
            DO UPDATE SET next_ticket_number = itsm.project_ticket_counter.next_ticket_number + 1,
                          updated_at = clock_timestamp()
            RETURNING next_ticket_number - 1 INTO v_number;
        END IF;

        NEW.ticket_number := v_number;
    END IF;

    SELECT project_key INTO v_project_key
      FROM config.service_project
     WHERE project_id = NEW.project_id;

    IF v_project_key IS NULL THEN
        RAISE EXCEPTION 'Unknown service project %', NEW.project_id;
    END IF;

    NEW.ticket_key := v_project_key || '-' || NEW.ticket_number::text;
    RETURN NEW;
END;
$$;

CREATE TRIGGER ticket_assign_key
BEFORE INSERT ON itsm.ticket
FOR EACH ROW EXECUTE FUNCTION itsm.assign_ticket_key();

CREATE OR REPLACE FUNCTION itsm.validate_ticket_workflow_status()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_status_workflow_version uuid;
BEGIN
    SELECT workflow_version_id
      INTO v_status_workflow_version
      FROM config.workflow_status
     WHERE status_id = NEW.status_id;

    IF v_status_workflow_version IS DISTINCT FROM NEW.workflow_version_id THEN
        RAISE EXCEPTION 'Status % does not belong to workflow version %',
            NEW.status_id, NEW.workflow_version_id;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER ticket_validate_workflow_status
BEFORE INSERT OR UPDATE OF workflow_version_id, status_id ON itsm.ticket
FOR EACH ROW EXECUTE FUNCTION itsm.validate_ticket_workflow_status();

CREATE OR REPLACE FUNCTION itsm.ticket_before_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    NEW.row_version := OLD.row_version + 1;
    RETURN NEW;
END;
$$;

CREATE TRIGGER ticket_set_version
BEFORE UPDATE ON itsm.ticket
FOR EACH ROW EXECUTE FUNCTION itsm.ticket_before_update();

CREATE TABLE itsm.ticket_participant (
    ticket_id         uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    user_id           uuid NOT NULL REFERENCES identity.app_user(user_id),
    participant_role  varchar(40) NOT NULL,
    notification_enabled boolean NOT NULL DEFAULT true,
    added_at          timestamptz NOT NULL DEFAULT now(),
    added_by          uuid REFERENCES identity.app_user(user_id),
    PRIMARY KEY (ticket_id, user_id, participant_role),
    CONSTRAINT participant_role_ck CHECK (
        participant_role IN (
            'REPORTER','REQUESTED_FOR','PARTICIPANT','WATCHER','APPROVER',
            'STAKEHOLDER','SERVICE_OWNER','MAJOR_INCIDENT_STAKEHOLDER'
        )
    )
);

CREATE TABLE itsm.ticket_comment (
    comment_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id         uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    author_user_id    uuid REFERENCES identity.app_user(user_id),
    visibility_code   varchar(30) NOT NULL,
    comment_body      text NOT NULL,
    source_channel    varchar(30),
    ai_generated_flag boolean NOT NULL DEFAULT false,
    ai_review_status  varchar(20),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT comment_visibility_ck CHECK (
        visibility_code IN ('PUBLIC','INTERNAL','SYSTEM','AI_GENERATED')
    ),
    CONSTRAINT comment_ai_review_ck CHECK (
        ai_review_status IS NULL OR ai_review_status IN ('DRAFT','APPROVED','REJECTED')
    )
);

CREATE TRIGGER ticket_comment_set_updated_at
BEFORE UPDATE ON itsm.ticket_comment
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE itsm.ticket_attachment (
    attachment_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id         uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    comment_id        uuid REFERENCES itsm.ticket_comment(comment_id) ON DELETE SET NULL,
    uploaded_by       uuid NOT NULL REFERENCES identity.app_user(user_id),
    original_filename varchar(500) NOT NULL,
    object_uri        text NOT NULL,
    content_type      varchar(200),
    file_size_bytes   bigint,
    sha256_checksum   varchar(64) NOT NULL,
    malware_scan_status varchar(30) NOT NULL DEFAULT 'PENDING',
    security_classification varchar(30) NOT NULL DEFAULT 'INTERNAL',
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT attachment_scan_ck CHECK (
        malware_scan_status IN ('PENDING','CLEAN','INFECTED','ERROR','QUARANTINED')
    )
);

CREATE TABLE itsm.ticket_custom_value (
    ticket_id         uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    custom_field_id   uuid NOT NULL REFERENCES config.custom_field(custom_field_id),
    text_value        text,
    number_value      numeric,
    date_value        date,
    timestamp_value   timestamptz,
    boolean_value     boolean,
    user_value        uuid REFERENCES identity.app_user(user_id),
    group_value       uuid REFERENCES identity.support_group(support_group_id),
    service_value     uuid REFERENCES config.service_node(service_node_id),
    option_value      uuid REFERENCES config.custom_field_option(option_id),
    json_value        jsonb,
    updated_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ticket_id, custom_field_id),
    CONSTRAINT custom_value_one_type_ck CHECK (
        num_nonnulls(
            text_value, number_value, date_value, timestamp_value,
            boolean_value, user_value, group_value,
            service_value, option_value, json_value
        ) <= 1
    )
);

CREATE TABLE itsm.ticket_link_type (
    link_type_code    varchar(50) PRIMARY KEY,
    outward_label     varchar(150) NOT NULL,
    inward_label      varchar(150) NOT NULL,
    symmetric_flag    boolean NOT NULL DEFAULT false
);

CREATE TABLE itsm.ticket_link (
    ticket_link_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_ticket_id  uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    target_ticket_id  uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    link_type_code    varchar(50) NOT NULL REFERENCES itsm.ticket_link_type(link_type_code),
    created_by        uuid NOT NULL REFERENCES identity.app_user(user_id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_ticket_id, target_ticket_id, link_type_code),
    CONSTRAINT ticket_link_no_self_ck CHECK (source_ticket_id <> target_ticket_id)
);

CREATE TABLE itsm.assignment_history (
    assignment_history_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id         uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    from_group_id     uuid REFERENCES identity.support_group(support_group_id),
    to_group_id       uuid REFERENCES identity.support_group(support_group_id),
    from_assignee_id  uuid REFERENCES identity.app_user(user_id),
    to_assignee_id    uuid REFERENCES identity.app_user(user_id),
    assignment_reason varchar(80) NOT NULL,
    routing_rule_id   uuid,
    assigned_by       uuid REFERENCES identity.app_user(user_id),
    assigned_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE itsm.ticket_event (
    event_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    ticket_id         uuid NOT NULL REFERENCES itsm.ticket(ticket_id) ON DELETE CASCADE,
    event_type        varchar(60) NOT NULL,
    actor_type        varchar(30) NOT NULL DEFAULT 'USER',
    actor_user_id     uuid REFERENCES identity.app_user(user_id),
    old_values_json   jsonb,
    new_values_json   jsonb,
    event_data_json   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ticket_event_actor_ck CHECK (
        actor_type IN ('USER','AGENT','SYSTEM','INTEGRATION','AI')
    )
);

CREATE OR REPLACE FUNCTION itsm.log_ticket_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_actor uuid := util.current_user_id();
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO itsm.ticket_event(
            tenant_id, ticket_id, event_type, actor_type, actor_user_id,
            new_values_json, event_data_json
        )
        VALUES (
            NEW.tenant_id, NEW.ticket_id, 'TICKET_CREATED',
            CASE WHEN NEW.ai_created_flag THEN 'AI' ELSE 'USER' END,
            COALESCE(v_actor, NEW.created_by), to_jsonb(NEW),
            jsonb_build_object('ticket_key', NEW.ticket_key)
        );
        RETURN NEW;
    END IF;

    INSERT INTO itsm.ticket_event(
        tenant_id, ticket_id, event_type, actor_type, actor_user_id,
        old_values_json, new_values_json
    )
    VALUES (
        NEW.tenant_id, NEW.ticket_id,
        CASE WHEN OLD.status_id IS DISTINCT FROM NEW.status_id
             THEN 'STATUS_CHANGED' ELSE 'TICKET_UPDATED' END,
        'USER', COALESCE(v_actor, NEW.updated_by),
        to_jsonb(OLD), to_jsonb(NEW)
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER ticket_log_insert
AFTER INSERT ON itsm.ticket
FOR EACH ROW EXECUTE FUNCTION itsm.log_ticket_change();

CREATE TRIGGER ticket_log_update
AFTER UPDATE ON itsm.ticket
FOR EACH ROW EXECUTE FUNCTION itsm.log_ticket_change();

COMMIT;
