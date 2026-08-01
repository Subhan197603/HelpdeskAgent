\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE config.work_type (
    work_type_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid REFERENCES identity.tenant(tenant_id),
    work_type_code   varchar(50) NOT NULL,
    work_type_name   varchar(150) NOT NULL,
    itsm_category    varchar(40) NOT NULL,
    active_flag      boolean NOT NULL DEFAULT true,
    UNIQUE NULLS NOT DISTINCT (tenant_id, work_type_code),
    CONSTRAINT work_type_category_ck CHECK (
        itsm_category IN (
            'SERVICE_REQUEST','INCIDENT','PROBLEM','CHANGE',
            'ACCESS_REQUEST','QUESTION','TASK','POST_INCIDENT_REVIEW'
        )
    )
);

CREATE TABLE config.workflow (
    workflow_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    workflow_code    varchar(100) NOT NULL,
    workflow_name    varchar(200) NOT NULL,
    description      text,
    active_flag      boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, workflow_code)
);

CREATE TABLE config.workflow_version (
    workflow_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id      uuid NOT NULL REFERENCES config.workflow(workflow_id),
    version_number   integer NOT NULL,
    version_status   varchar(20) NOT NULL DEFAULT 'DRAFT',
    effective_from   timestamptz,
    effective_to     timestamptz,
    published_at     timestamptz,
    published_by     uuid REFERENCES identity.app_user(user_id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workflow_id, version_number),
    CONSTRAINT workflow_version_status_ck CHECK (
        version_status IN ('DRAFT','PUBLISHED','RETIRED')
    )
);

CREATE TABLE config.workflow_status (
    status_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_version_id uuid NOT NULL REFERENCES config.workflow_version(workflow_version_id),
    status_code      varchar(80) NOT NULL,
    status_name      varchar(150) NOT NULL,
    status_category  varchar(20) NOT NULL,
    initial_flag     boolean NOT NULL DEFAULT false,
    terminal_flag    boolean NOT NULL DEFAULT false,
    customer_visible_name varchar(150),
    display_order    integer NOT NULL DEFAULT 0,
    UNIQUE (workflow_version_id, status_code),
    CONSTRAINT workflow_status_category_ck CHECK (
        status_category IN ('TO_DO','IN_PROGRESS','WAITING','DONE','CANCELLED')
    )
);

CREATE UNIQUE INDEX workflow_one_initial_status_ux
ON config.workflow_status (workflow_version_id)
WHERE initial_flag;

CREATE TABLE config.workflow_transition (
    transition_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_version_id uuid NOT NULL REFERENCES config.workflow_version(workflow_version_id),
    transition_code  varchar(100) NOT NULL,
    transition_name  varchar(200) NOT NULL,
    from_status_id   uuid NOT NULL REFERENCES config.workflow_status(status_id),
    to_status_id     uuid NOT NULL REFERENCES config.workflow_status(status_id),
    condition_json   jsonb NOT NULL DEFAULT '[]'::jsonb,
    validator_json   jsonb NOT NULL DEFAULT '[]'::jsonb,
    action_json      jsonb NOT NULL DEFAULT '[]'::jsonb,
    display_order    integer NOT NULL DEFAULT 0,
    active_flag      boolean NOT NULL DEFAULT true,
    UNIQUE (workflow_version_id, transition_code)
);

CREATE TABLE config.request_type (
    request_type_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    project_id       uuid NOT NULL REFERENCES config.service_project(project_id),
    work_type_id     uuid NOT NULL REFERENCES config.work_type(work_type_id),
    workflow_id      uuid NOT NULL REFERENCES config.workflow(workflow_id),
    request_type_code varchar(100) NOT NULL,
    request_type_name varchar(200) NOT NULL,
    portal_description text,
    portal_group     varchar(150),
    icon_name        varchar(100),
    employee_visible_flag boolean NOT NULL DEFAULT true,
    active_flag      boolean NOT NULL DEFAULT true,
    display_order    integer NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, request_type_code)
);

CREATE TRIGGER request_type_set_updated_at
BEFORE UPDATE ON config.request_type
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE config.custom_field (
    custom_field_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    field_code       varchar(100) NOT NULL,
    field_name       varchar(200) NOT NULL,
    data_type        varchar(30) NOT NULL,
    searchable_flag  boolean NOT NULL DEFAULT false,
    reportable_flag  boolean NOT NULL DEFAULT false,
    security_classification varchar(30) NOT NULL DEFAULT 'INTERNAL',
    validation_json  jsonb NOT NULL DEFAULT '{}'::jsonb,
    active_flag      boolean NOT NULL DEFAULT true,
    UNIQUE (tenant_id, field_code),
    CONSTRAINT custom_field_data_type_ck CHECK (
        data_type IN (
            'TEXT','LONG_TEXT','NUMBER','DATE','TIMESTAMP','BOOLEAN',
            'SINGLE_SELECT','MULTI_SELECT','USER','GROUP','SERVICE',
            'MODULE','ASSET','JSON_OBJECT'
        )
    )
);

CREATE TABLE config.custom_field_option (
    option_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    custom_field_id  uuid NOT NULL REFERENCES config.custom_field(custom_field_id),
    option_code      varchar(100) NOT NULL,
    option_label     varchar(200) NOT NULL,
    parent_option_id uuid REFERENCES config.custom_field_option(option_id),
    display_order    integer NOT NULL DEFAULT 0,
    active_flag      boolean NOT NULL DEFAULT true,
    UNIQUE (custom_field_id, option_code)
);

CREATE TABLE config.request_type_field (
    request_type_id  uuid NOT NULL REFERENCES config.request_type(request_type_id),
    custom_field_id  uuid NOT NULL REFERENCES config.custom_field(custom_field_id),
    display_label    varchar(200),
    help_text        text,
    display_order    integer NOT NULL DEFAULT 0,
    required_flag    boolean NOT NULL DEFAULT false,
    hidden_flag      boolean NOT NULL DEFAULT false,
    default_value_json jsonb,
    condition_json   jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (request_type_id, custom_field_id)
);

COMMIT;
