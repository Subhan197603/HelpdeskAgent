\set ON_ERROR_STOP on
\echo 'Installing Fusion Helpdesk PostgreSQL schema...'
\ir 00_prerequisites.sql
\ir 01_foundation.sql
\ir 02_catalog_workflow.sql
\ir 03_ticketing.sql
\ir 04_routing_sla_approval.sql
\ir 05_knowledge.sql
\ir 06_ai_audit_integration.sql
\ir 06a_foundational_governance.sql
\ir 07_indexes_views_search.sql
\ir 08_seed_reference.sql
\ir 08a_runtime_privileges.sql
\echo 'Base installation completed.'
\echo '09_optional_rls.sql is intentionally not applied automatically.'
