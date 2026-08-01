\set ON_ERROR_STOP on

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helpdesk_owner') THEN
        CREATE ROLE helpdesk_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helpdesk_migrator') THEN
        CREATE ROLE helpdesk_migrator NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helpdesk_app') THEN
        CREATE ROLE helpdesk_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helpdesk_worker') THEN
        CREATE ROLE helpdesk_worker NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helpdesk_reporting') THEN
        CREATE ROLE helpdesk_reporting NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helpdesk_readonly') THEN
        CREATE ROLE helpdesk_readonly NOLOGIN;
    END IF;
END;
$$;

GRANT helpdesk_owner TO helpdesk_migrator;

CREATE SCHEMA IF NOT EXISTS util AUTHORIZATION helpdesk_owner;
CREATE SCHEMA IF NOT EXISTS identity AUTHORIZATION helpdesk_owner;
CREATE SCHEMA IF NOT EXISTS config AUTHORIZATION helpdesk_owner;
CREATE SCHEMA IF NOT EXISTS itsm AUTHORIZATION helpdesk_owner;
CREATE SCHEMA IF NOT EXISTS kb AUTHORIZATION helpdesk_owner;
CREATE SCHEMA IF NOT EXISTS ai AUTHORIZATION helpdesk_owner;
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION helpdesk_owner;
CREATE SCHEMA IF NOT EXISTS integration AUTHORIZATION helpdesk_owner;

SET ROLE helpdesk_owner;

CREATE OR REPLACE FUNCTION util.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION util.reject_immutable_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE OR REPLACE FUNCTION util.protect_published_configuration()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.version_status IN ('PUBLISHED', 'RETIRED') THEN
        RAISE EXCEPTION 'Published or retired configuration versions are immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE OR REPLACE FUNCTION util.current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION util.current_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.user_id', true), '')::uuid;
$$;

COMMIT;
