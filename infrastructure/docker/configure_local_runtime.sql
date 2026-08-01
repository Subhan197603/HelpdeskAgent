\set ON_ERROR_STOP on

-- Local development login only. Production identity and credential provisioning are external.
SELECT format('CREATE ROLE helpdesk LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'helpdesk') \gexec
SELECT format('ALTER ROLE helpdesk WITH LOGIN PASSWORD %L', :'app_password') \gexec
GRANT helpdesk_app TO helpdesk;
