\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE identity.tenant (
    tenant_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_code     varchar(50) NOT NULL UNIQUE,
    tenant_name     varchar(200) NOT NULL,
    default_timezone varchar(80) NOT NULL DEFAULT 'UTC',
    active_flag     boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER tenant_set_updated_at
BEFORE UPDATE ON identity.tenant
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE identity.business_unit (
    business_unit_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    business_unit_code varchar(80) NOT NULL,
    business_unit_name varchar(200) NOT NULL,
    parent_business_unit_id uuid REFERENCES identity.business_unit(business_unit_id),
    active_flag      boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, business_unit_code)
);

CREATE TRIGGER business_unit_set_updated_at
BEFORE UPDATE ON identity.business_unit
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE identity.app_user (
    user_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    external_subject varchar(300) NOT NULL,
    email_address    varchar(320) NOT NULL,
    display_name     varchar(250) NOT NULL,
    employee_number  varchar(100),
    business_unit_id uuid REFERENCES identity.business_unit(business_unit_id),
    manager_user_id  uuid REFERENCES identity.app_user(user_id),
    locale_code      varchar(20) NOT NULL DEFAULT 'en',
    timezone_name    varchar(80) NOT NULL DEFAULT 'UTC',
    active_flag      boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, external_subject),
    UNIQUE (tenant_id, email_address)
);

CREATE TRIGGER app_user_set_updated_at
BEFORE UPDATE ON identity.app_user
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE identity.role_definition (
    role_code        varchar(60) PRIMARY KEY,
    role_name        varchar(150) NOT NULL,
    description      text,
    system_role_flag boolean NOT NULL DEFAULT true
);

CREATE TABLE identity.user_role (
    tenant_id        uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    user_id          uuid NOT NULL REFERENCES identity.app_user(user_id),
    role_code        varchar(60) NOT NULL REFERENCES identity.role_definition(role_code),
    valid_from       timestamptz NOT NULL DEFAULT now(),
    valid_to         timestamptz,
    granted_by       uuid REFERENCES identity.app_user(user_id),
    PRIMARY KEY (tenant_id, user_id, role_code, valid_from)
);

CREATE TABLE identity.support_group (
    support_group_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    group_code       varchar(100) NOT NULL,
    group_name       varchar(200) NOT NULL,
    email_address    varchar(320),
    manager_user_id  uuid REFERENCES identity.app_user(user_id),
    assignment_method varchar(40) NOT NULL DEFAULT 'GROUP_ONLY',
    active_flag      boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, group_code),
    CONSTRAINT support_group_assignment_method_ck CHECK (
        assignment_method IN (
            'GROUP_ONLY','ROUND_ROBIN','LEAST_OPEN_TICKETS',
            'LEAST_WEIGHTED_WORKLOAD','SKILL_BASED','MANUAL','NAMED_ASSIGNEE'
        )
    )
);

CREATE TRIGGER support_group_set_updated_at
BEFORE UPDATE ON identity.support_group
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE identity.support_group_member (
    support_group_id uuid NOT NULL REFERENCES identity.support_group(support_group_id),
    user_id          uuid NOT NULL REFERENCES identity.app_user(user_id),
    member_role      varchar(30) NOT NULL DEFAULT 'AGENT',
    capacity_points  numeric(10,2) NOT NULL DEFAULT 10,
    active_flag      boolean NOT NULL DEFAULT true,
    joined_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (support_group_id, user_id),
    CONSTRAINT support_group_member_role_ck CHECK (
        member_role IN ('AGENT','LEAD','MANAGER','OBSERVER')
    )
);

CREATE TABLE config.service_project (
    project_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    project_key      varchar(12) NOT NULL,
    project_name     varchar(200) NOT NULL,
    description      text,
    default_group_id uuid REFERENCES identity.support_group(support_group_id),
    default_timezone varchar(80) NOT NULL DEFAULT 'UTC',
    active_flag      boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, project_key)
);

CREATE TRIGGER service_project_set_updated_at
BEFORE UPDATE ON config.service_project
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE config.service_node (
    service_node_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid REFERENCES identity.tenant(tenant_id),
    parent_node_id   uuid REFERENCES config.service_node(service_node_id),
    node_code        varchar(120) NOT NULL,
    node_name        varchar(250) NOT NULL,
    node_type        varchar(30) NOT NULL,
    owner_group_id   uuid REFERENCES identity.support_group(support_group_id),
    active_flag      boolean NOT NULL DEFAULT true,
    display_order    integer NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, node_code),
    CONSTRAINT service_node_type_ck CHECK (
        node_type IN ('SERVICE_FAMILY','SERVICE','MODULE','BUSINESS_PROCESS','COMPONENT')
    )
);

CREATE TRIGGER service_node_set_updated_at
BEFORE UPDATE ON config.service_node
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE config.category (
    category_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    parent_category_id uuid REFERENCES config.category(category_id),
    category_code    varchar(100) NOT NULL,
    category_name    varchar(200) NOT NULL,
    active_flag      boolean NOT NULL DEFAULT true,
    UNIQUE (tenant_id, category_code)
);

CREATE TABLE config.priority (
    priority_code    varchar(20) PRIMARY KEY,
    priority_name    varchar(100) NOT NULL,
    rank_order       integer NOT NULL UNIQUE,
    workload_weight  numeric(10,2) NOT NULL DEFAULT 1,
    active_flag      boolean NOT NULL DEFAULT true
);

CREATE TABLE config.channel (
    channel_code     varchar(30) PRIMARY KEY,
    channel_name     varchar(100) NOT NULL,
    active_flag      boolean NOT NULL DEFAULT true
);

CREATE TABLE config.environment (
    environment_code varchar(30) PRIMARY KEY,
    environment_name varchar(100) NOT NULL,
    production_flag  boolean NOT NULL DEFAULT false,
    active_flag      boolean NOT NULL DEFAULT true
);

CREATE TABLE config.resolution_code (
    resolution_code  varchar(50) PRIMARY KEY,
    resolution_name  varchar(150) NOT NULL,
    active_flag      boolean NOT NULL DEFAULT true
);

COMMIT;
