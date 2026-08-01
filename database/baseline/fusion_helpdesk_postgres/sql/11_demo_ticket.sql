\set ON_ERROR_STOP on

-- Requires 10_demo_bootstrap.sql.
INSERT INTO itsm.ticket(
    tenant_id, project_id, request_type_id, request_type_version_id, work_type_id,
    workflow_version_id, status_id, summary, description,
    reporter_user_id, requested_for_user_id, business_unit_id,
    service_node_id, category_id, priority_code,
    assignment_group_id, channel_code, environment_code,
    created_by, updated_by, ai_created_flag, ai_classification_score
)
SELECT
    '10000000-0000-0000-0000-000000000001',
    '14000000-0000-0000-0000-000000000001',
    '18000000-0000-0000-0000-000000000002',
    '18100000-0000-0000-0000-000000000002',
    wt.work_type_id,
    '17100000-0000-0000-0000-000000000001',
    '17200000-0000-0000-0000-000000000001',
    'OTBI analysis returns incorrect invoice total',
    'The invoice total differs from the Accounts Payable source report.',
    '12000000-0000-0000-0000-000000000002',
    '12000000-0000-0000-0000-000000000002',
    '11000000-0000-0000-0000-000000000001',
    '15000000-0000-0000-0000-000000000006',
    '16000000-0000-0000-0000-000000000004',
    'P3',
    '13000000-0000-0000-0000-000000000002',
    'CHAT','PROD',
    '12000000-0000-0000-0000-000000000002',
    '12000000-0000-0000-0000-000000000002',
    true,0.94
FROM config.work_type wt
WHERE wt.tenant_id IS NULL AND wt.work_type_code = 'INCIDENT'
RETURNING ticket_key, ticket_id, summary;
