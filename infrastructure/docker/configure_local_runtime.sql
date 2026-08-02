\set ON_ERROR_STOP on

-- Local development login only. Production identity and credential provisioning are external.
SELECT format('CREATE ROLE helpdesk LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'helpdesk') \gexec
SELECT format('ALTER ROLE helpdesk WITH LOGIN PASSWORD %L', :'app_password') \gexec
GRANT helpdesk_app TO helpdesk;

SELECT format('CREATE ROLE helpdesk_worker_login LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'helpdesk_worker_login') \gexec
SELECT format('ALTER ROLE helpdesk_worker_login WITH LOGIN PASSWORD %L', :'app_password') \gexec
GRANT helpdesk_worker TO helpdesk_worker_login;
