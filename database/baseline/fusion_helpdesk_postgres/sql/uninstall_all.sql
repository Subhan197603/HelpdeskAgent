\set ON_ERROR_STOP on

-- LOCAL DEVELOPMENT ONLY. This script is not a production rollback.
-- Run with: psql ... -v confirm_local_uninstall=true -f uninstall_all.sql
\if :{?confirm_local_uninstall}
\else
\echo 'Refusing uninstall: pass -v confirm_local_uninstall=true for a local database.'
\quit
\endif

\if :confirm_local_uninstall
\else
\echo 'Refusing uninstall: confirm_local_uninstall must be true.'
\quit
\endif

DO $$
BEGIN
    IF current_database() <> 'helpdesk' THEN
        RAISE EXCEPTION 'Refusing uninstall outside the local helpdesk database';
    END IF;
END;
$$;

-- DESTRUCTIVE: removes all package schemas and data from local helpdesk only.
DROP SCHEMA IF EXISTS integration CASCADE;
DROP SCHEMA IF EXISTS audit CASCADE;
DROP SCHEMA IF EXISTS ai CASCADE;
DROP SCHEMA IF EXISTS kb CASCADE;
DROP SCHEMA IF EXISTS itsm CASCADE;
DROP SCHEMA IF EXISTS config CASCADE;
DROP SCHEMA IF EXISTS identity CASCADE;
DROP SCHEMA IF EXISTS util CASCADE;
