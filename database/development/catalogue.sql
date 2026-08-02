\set ON_ERROR_STOP on

BEGIN;

INSERT INTO config.service_project(
    project_id, tenant_id, project_key, project_name, description, default_timezone
) VALUES
('30000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','IT','Corporate IT Helpdesk','General corporate technology support.','Europe/London'),
('30000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','ERP','Oracle Fusion ERP Support','Oracle Fusion ERP functional and technical support.','Europe/London'),
('30000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000001','HCM','Oracle Fusion HCM Support','Oracle Fusion HCM support.','Europe/London'),
('30000000-0000-0000-0000-000000000004','20000000-0000-0000-0000-000000000001','SCM','Oracle Fusion SCM Support','Oracle Fusion SCM support.','Europe/London'),
('30000000-0000-0000-0000-000000000005','20000000-0000-0000-0000-000000000001','BI','Analytics and Reporting Support','OTBI, BI Publisher, OAC, and FDI support.','Europe/London'),
('30000000-0000-0000-0000-000000000006','20000000-0000-0000-0000-000000000001','SEC','Identity and Security','Identity, authentication, and access support.','Europe/London')
ON CONFLICT (project_id) DO NOTHING;

INSERT INTO config.service_node(
    service_node_id, tenant_id, parent_node_id, node_code, node_name,
    node_type, display_order, criticality_code, data_classification
) VALUES
('31000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',NULL,'CORPORATE_IT','Corporate IT','BUSINESS_SERVICE',10,'HIGH','INTERNAL'),
('31000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001',NULL,'ORACLE_FUSION','Oracle Fusion Cloud Applications','SERVICE_FAMILY',20,'HIGH','INTERNAL'),
('31000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000001','31000000-0000-0000-0000-000000000002','ERP','Enterprise Resource Planning','APPLICATION',10,'HIGH','INTERNAL'),
('31000000-0000-0000-0000-000000000004','20000000-0000-0000-0000-000000000001','31000000-0000-0000-0000-000000000002','HCM','Human Capital Management','APPLICATION',20,'HIGH','CONFIDENTIAL'),
('31000000-0000-0000-0000-000000000006','20000000-0000-0000-0000-000000000001',NULL,'INACTIVE_NODE','Inactive service','SERVICE',1,NULL,'INTERNAL')
ON CONFLICT (service_node_id) DO NOTHING;

UPDATE config.service_node
SET active_flag = false
WHERE service_node_id = '31000000-0000-0000-0000-000000000006';

INSERT INTO config.workflow(
    workflow_id, tenant_id, workflow_code, workflow_name, description
) VALUES (
    '32000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'CATALOGUE_TEST_WORKFLOW', 'Catalogue fixture workflow',
    'Deterministic incident workflow used by development and integration tests.'
) ON CONFLICT (workflow_id) DO NOTHING;

INSERT INTO config.workflow_version(
    workflow_version_id, workflow_id, version_number, version_status,
    effective_from, published_at, published_by
) VALUES (
    '32100000-0000-0000-0000-000000000001',
    '32000000-0000-0000-0000-000000000001', 1, 'DRAFT',
    '2025-01-01T00:00:00Z', NULL, NULL
) ON CONFLICT (workflow_version_id) DO NOTHING;

INSERT INTO config.workflow_status(
    status_id, workflow_version_id, status_code, status_name,
    status_category, initial_flag, customer_visible_name, display_order
) VALUES (
    '32200000-0000-0000-0000-000000000001',
    '32100000-0000-0000-0000-000000000001',
    'NEW', 'New', 'TO_DO', true, 'Submitted', 10
) ON CONFLICT (status_id) DO NOTHING;

INSERT INTO config.workflow_status(
    status_id, workflow_version_id, status_code, status_name,
    status_category, terminal_flag, customer_visible_name, display_order
) VALUES
('32200000-0000-0000-0000-000000000002','32100000-0000-0000-0000-000000000001','IN_PROGRESS','In progress','IN_PROGRESS',false,'In progress',20),
('32200000-0000-0000-0000-000000000003','32100000-0000-0000-0000-000000000001','WAITING_FOR_CUSTOMER','Waiting for customer','WAITING',false,'Waiting for you',30),
('32200000-0000-0000-0000-000000000004','32100000-0000-0000-0000-000000000001','RESOLVED','Resolved','DONE',false,'Resolved',40),
('32200000-0000-0000-0000-000000000005','32100000-0000-0000-0000-000000000001','CLOSED','Closed','DONE',true,'Closed',50)
ON CONFLICT (status_id) DO NOTHING;

INSERT INTO config.workflow_transition(
    transition_id, workflow_version_id, transition_code, transition_name,
    from_status_id, to_status_id, condition_json, validator_json, action_json,
    display_order
) VALUES
('32300000-0000-0000-0000-000000000001','32100000-0000-0000-0000-000000000001','START_PROGRESS','Start progress','32200000-0000-0000-0000-000000000001','32200000-0000-0000-0000-000000000002','[]','[]','[{"type":"SET_TIMESTAMP","field":"first_response_at"}]',10),
('32300000-0000-0000-0000-000000000002','32100000-0000-0000-0000-000000000001','WAIT_FOR_CUSTOMER','Wait for customer','32200000-0000-0000-0000-000000000002','32200000-0000-0000-0000-000000000003','{"all":[{"field":"summary","operator":"is_not_null"}]}','[]','[]',20),
('32300000-0000-0000-0000-000000000003','32100000-0000-0000-0000-000000000001','RESUME_PROGRESS','Resume progress','32200000-0000-0000-0000-000000000003','32200000-0000-0000-0000-000000000002','[]','[]','[]',30),
('32300000-0000-0000-0000-000000000004','32100000-0000-0000-0000-000000000001','RESOLVE','Resolve','32200000-0000-0000-0000-000000000002','32200000-0000-0000-0000-000000000004','[]','[{"type":"required_field","field":"resolution_code"}]','[{"type":"SET_TIMESTAMP","field":"resolved_at"}]',40),
('32300000-0000-0000-0000-000000000005','32100000-0000-0000-0000-000000000001','REOPEN','Reopen','32200000-0000-0000-0000-000000000004','32200000-0000-0000-0000-000000000002','[]','[]','[{"type":"CLEAR_FIELD","field":"resolved_at"},{"type":"CLEAR_FIELD","field":"resolution_code"},{"type":"CLEAR_FIELD","field":"resolution_summary"}]',50),
('32300000-0000-0000-0000-000000000006','32100000-0000-0000-0000-000000000001','CLOSE','Close','32200000-0000-0000-0000-000000000004','32200000-0000-0000-0000-000000000005','[]','[]','[{"type":"SET_TIMESTAMP","field":"closed_at"}]',60)
ON CONFLICT (transition_id) DO NOTHING;

UPDATE config.workflow_version
SET version_status = 'PUBLISHED',
    published_at = '2025-01-01T00:00:00Z',
    published_by = '22000000-0000-0000-0000-000000000001'
WHERE workflow_version_id = '32100000-0000-0000-0000-000000000001'
  AND version_status = 'DRAFT';

INSERT INTO config.request_type(
    request_type_id, tenant_id, project_id, work_type_id, workflow_id,
    request_type_code, request_type_name, portal_description, portal_group, display_order
)
SELECT
    fixture.request_type_id,
    '20000000-0000-0000-0000-000000000001', fixture.project_id,
    work_type.work_type_id, '32000000-0000-0000-0000-000000000001',
    fixture.request_type_code, fixture.request_type_name,
    fixture.portal_description, fixture.portal_group, fixture.display_order
FROM (VALUES
    ('33000000-0000-0000-0000-000000000001'::uuid,'30000000-0000-0000-0000-000000000002'::uuid,'INCIDENT','REPORT_FUSION_ERROR','Report an Oracle Fusion error','Report an issue affecting Oracle Fusion.','Oracle Fusion',10),
    ('33000000-0000-0000-0000-000000000002'::uuid,'30000000-0000-0000-0000-000000000006'::uuid,'ACCESS_REQUEST','REQUEST_FUSION_ACCESS','Request access to Oracle Fusion','Request approved access to an Oracle Fusion service.','Access',10),
    ('33000000-0000-0000-0000-000000000003'::uuid,'30000000-0000-0000-0000-000000000005'::uuid,'INCIDENT','REPORT_ANALYTICS_ISSUE','Report an analytics issue','Report an OTBI, BI Publisher, OAC, or FDI issue.','Analytics',10),
    ('33000000-0000-0000-0000-000000000004'::uuid,'30000000-0000-0000-0000-000000000005'::uuid,'SERVICE_REQUEST','REQUEST_NEW_REPORT','Request a new report or dashboard','Request a governed analytics artefact.','Analytics',20),
    ('33000000-0000-0000-0000-000000000005'::uuid,'30000000-0000-0000-0000-000000000002'::uuid,'INCIDENT','REPORT_DATA_ISSUE','Report incorrect or missing data','Report a data-quality issue.','Oracle Fusion',20),
    ('33000000-0000-0000-0000-000000000006'::uuid,'30000000-0000-0000-0000-000000000002'::uuid,'INCIDENT','REPORT_INTEGRATION_FAILURE','Report an integration failure','Report a failed integration.','Oracle Fusion',30),
    ('33000000-0000-0000-0000-000000000007'::uuid,'30000000-0000-0000-0000-000000000002'::uuid,'INCIDENT','REPORT_SCHEDULED_PROCESS_FAILURE','Report a scheduled-process failure','Report a failed scheduled process.','Oracle Fusion',40),
    ('33000000-0000-0000-0000-000000000008'::uuid,'30000000-0000-0000-0000-000000000001'::uuid,'QUESTION','GENERAL_IT_QUESTION','General IT question','Ask the Corporate IT team a question.','General',10),
    ('33000000-0000-0000-0000-000000000009'::uuid,'30000000-0000-0000-0000-000000000001'::uuid,'INCIDENT','BASIC_INCIDENT','Report a general incident','Report an interruption or degradation.','General',20)
) AS fixture(
    request_type_id, project_id, work_type_code, request_type_code,
    request_type_name, portal_description, portal_group, display_order
)
JOIN config.work_type AS work_type
  ON work_type.work_type_code = fixture.work_type_code
 AND work_type.tenant_id IS NULL
ON CONFLICT (request_type_id) DO NOTHING;

INSERT INTO config.request_type_version(
    request_type_version_id, request_type_id, version_number, version_status,
    form_schema_json, effective_from, created_by, approved_by, approved_at,
    change_reason, published_at
)
SELECT
    ('33100000-0000-0000-0000-' || right(request_type_id::text, 12))::uuid,
    request_type_id, 1, 'DRAFT', '{}', '2025-01-01T00:00:00Z',
    '22000000-0000-0000-0000-000000000001',
    '22000000-0000-0000-0000-000000000001', '2025-01-01T00:00:00Z',
    'Deterministic development fixture', NULL
FROM config.request_type
WHERE request_type_id BETWEEN
    '33000000-0000-0000-0000-000000000001' AND
    '33000000-0000-0000-0000-000000000009'
ON CONFLICT (request_type_version_id) DO NOTHING;

INSERT INTO config.custom_field(
    custom_field_id, tenant_id, field_code, field_name, data_type, validation_json
) VALUES
('34000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','summary','Brief summary','TEXT','{"minimum_length":5,"maximum_length":200}'),
('34000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','description','Detailed description','LONG_TEXT','{"minimum_length":10,"maximum_length":5000}'),
('34000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000001','environment','Environment','SINGLE_SELECT','{}')
ON CONFLICT (custom_field_id) DO NOTHING;

INSERT INTO config.custom_field_option(
    option_id, custom_field_id, option_code, option_label, display_order
) VALUES
('34100000-0000-0000-0000-000000000001','34000000-0000-0000-0000-000000000003','PROD','Production',10),
('34100000-0000-0000-0000-000000000002','34000000-0000-0000-0000-000000000003','TEST','Test',20),
('34100000-0000-0000-0000-000000000003','34000000-0000-0000-0000-000000000003','RETIRED','Retired environment',30)
ON CONFLICT (option_id) DO NOTHING;

UPDATE config.custom_field_option
SET active_flag = false
WHERE option_id = '34100000-0000-0000-0000-000000000003';

INSERT INTO config.request_type_field(
    request_type_version_id, custom_field_id, display_label, help_text,
    display_order, required_flag, condition_json
)
SELECT version.request_type_version_id, field.custom_field_id,
       field.field_name, NULL,
       CASE field.field_code WHEN 'summary' THEN 10 ELSE 20 END,
       true, '{}'
FROM config.request_type_version AS version
CROSS JOIN config.custom_field AS field
WHERE version.request_type_id BETWEEN
        '33000000-0000-0000-0000-000000000001' AND
        '33000000-0000-0000-0000-000000000009'
  AND field.custom_field_id IN (
        '34000000-0000-0000-0000-000000000001',
        '34000000-0000-0000-0000-000000000002'
  )
ON CONFLICT (request_type_version_id, custom_field_id) DO NOTHING;

INSERT INTO config.request_type_field(
    request_type_version_id, custom_field_id, display_label, help_text,
    display_order, required_flag, condition_json
) VALUES (
    '33100000-0000-0000-0000-000000000001',
    '34000000-0000-0000-0000-000000000003',
    'Affected environment', 'Select the environment affected by the issue.',
    30, true,
    '{"all":[{"field":"summary","operator":"is_not_empty","value":null}]}'
) ON CONFLICT (request_type_version_id, custom_field_id) DO NOTHING;

UPDATE config.request_type_version
SET version_status = 'PUBLISHED',
    published_at = '2025-01-01T00:00:00Z'
WHERE request_type_id BETWEEN
    '33000000-0000-0000-0000-000000000001' AND
    '33000000-0000-0000-0000-000000000009'
  AND version_status = 'DRAFT';

COMMIT;
