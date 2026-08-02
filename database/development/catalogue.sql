\set ON_ERROR_STOP on

BEGIN;

INSERT INTO config.service_project(
    project_id, tenant_id, project_key, project_name, description, default_timezone,
    default_group_id
) VALUES
('30000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','IT','Corporate IT Helpdesk','General corporate technology support.','Europe/London','23000000-0000-0000-0000-000000000001'),
('30000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','ERP','Oracle Fusion ERP Support','Oracle Fusion ERP functional and technical support.','Europe/London','23000000-0000-0000-0000-000000000001'),
('30000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000001','HCM','Oracle Fusion HCM Support','Oracle Fusion HCM support.','Europe/London','23000000-0000-0000-0000-000000000001'),
('30000000-0000-0000-0000-000000000004','20000000-0000-0000-0000-000000000001','SCM','Oracle Fusion SCM Support','Oracle Fusion SCM support.','Europe/London','23000000-0000-0000-0000-000000000001'),
('30000000-0000-0000-0000-000000000005','20000000-0000-0000-0000-000000000001','BI','Analytics and Reporting Support','OTBI, BI Publisher, OAC, and FDI support.','Europe/London','23000000-0000-0000-0000-000000000001'),
('30000000-0000-0000-0000-000000000006','20000000-0000-0000-0000-000000000001','SEC','Identity and Security','Identity, authentication, and access support.','Europe/London','23000000-0000-0000-0000-000000000001')
ON CONFLICT (project_id) DO NOTHING;

INSERT INTO config.service_node(
    service_node_id, tenant_id, parent_node_id, node_code, node_name,
    node_type, display_order, criticality_code, data_classification
) VALUES
('31000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',NULL,'CORPORATE_IT','Corporate IT','BUSINESS_SERVICE',10,'HIGH','INTERNAL'),
('31000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001',NULL,'ORACLE_FUSION','Oracle Fusion Cloud Applications','SERVICE_FAMILY',20,'HIGH','INTERNAL'),
('31000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000001','31000000-0000-0000-0000-000000000002','ERP','Enterprise Resource Planning','APPLICATION',10,'HIGH','INTERNAL'),
('31000000-0000-0000-0000-000000000004','20000000-0000-0000-0000-000000000001','31000000-0000-0000-0000-000000000002','HCM','Human Capital Management','APPLICATION',20,'HIGH','CONFIDENTIAL'),
('31000000-0000-0000-0000-000000000005','20000000-0000-0000-0000-000000000001','31000000-0000-0000-0000-000000000003','ACCOUNTS_PAYABLE','Accounts Payable','MODULE',10,'HIGH','INTERNAL'),
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
('32200000-0000-0000-0000-000000000005','32100000-0000-0000-0000-000000000001','CLOSED','Closed','DONE',true,'Closed',50),
('32200000-0000-0000-0000-000000000006','32100000-0000-0000-0000-000000000001','AWAITING_APPROVAL','Awaiting approval','WAITING',false,'Awaiting approval',60),
('32200000-0000-0000-0000-000000000007','32100000-0000-0000-0000-000000000001','REJECTED','Rejected','DONE',true,'Rejected',70)
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
('32300000-0000-0000-0000-000000000006','32100000-0000-0000-0000-000000000001','CLOSE','Close','32200000-0000-0000-0000-000000000004','32200000-0000-0000-0000-000000000005','[]','[]','[{"type":"SET_TIMESTAMP","field":"closed_at"}]',60),
('32300000-0000-0000-0000-000000000007','32100000-0000-0000-0000-000000000001','REQUEST_APPROVAL','Request approval','32200000-0000-0000-0000-000000000001','32200000-0000-0000-0000-000000000006','{"field":"work_type_code","operator":"equals","value":"ACCESS_REQUEST"}','[]','[{"type":"CREATE_APPROVAL","approval_code":"ACCESS_MANAGER"}]',70),
('32300000-0000-0000-0000-000000000008','32100000-0000-0000-0000-000000000001','APPROVE_ACCESS','Approval accepted','32200000-0000-0000-0000-000000000006','32200000-0000-0000-0000-000000000002','[]','[]','[{"type":"APPROVAL_CONTINUATION"}]',80),
('32300000-0000-0000-0000-000000000009','32100000-0000-0000-0000-000000000001','REJECT_ACCESS','Approval rejected','32200000-0000-0000-0000-000000000006','32200000-0000-0000-0000-000000000007','[]','[]','[{"type":"APPROVAL_CONTINUATION"}]',90)
ON CONFLICT (transition_id) DO NOTHING;

INSERT INTO config.approval_definition(
    approval_definition_id,tenant_id,project_id,approval_code,approval_name,
    approval_mode,approver_rule_json,on_approved_transition_id,
    on_rejected_transition_id
) VALUES (
    '38600000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000006',
    'ACCESS_MANAGER','Manager approval for access','MANAGER_APPROVAL',
    '{"subject":"REQUESTED_FOR_OR_REPORTER","rejection_comment_required":true}',
    '32300000-0000-0000-0000-000000000008',
    '32300000-0000-0000-0000-000000000009'
) ON CONFLICT (approval_definition_id) DO NOTHING;

INSERT INTO config.approval_definition_version(
    approval_definition_version_id,approval_definition_id,version_number,
    version_status,approval_mode,approver_rule_json,on_approved_transition_id,
    on_rejected_transition_id,effective_from,created_by,approved_by,approved_at,
    change_reason,allow_requester_self_approval,expires_after_minutes
) VALUES (
    '38700000-0000-0000-0000-000000000001',
    '38600000-0000-0000-0000-000000000001',1,'DRAFT','MANAGER_APPROVAL',
    '{"subject":"REQUESTED_FOR_OR_REPORTER","rejection_comment_required":true}',
    '32300000-0000-0000-0000-000000000008',
    '32300000-0000-0000-0000-000000000009','2025-01-01T00:00:00Z',
    '22000000-0000-0000-0000-000000000001',
    '22000000-0000-0000-0000-000000000001','2025-01-01T00:00:00Z',
    'Initial manager approval for access',false,10080
) ON CONFLICT (approval_definition_version_id) DO NOTHING;

UPDATE config.approval_definition_version
SET version_status='PUBLISHED',published_at='2025-01-01T00:00:00Z'
WHERE approval_definition_version_id='38700000-0000-0000-0000-000000000001'
  AND version_status='DRAFT';

UPDATE config.workflow_version
SET version_status = 'PUBLISHED',
    published_at = '2025-01-01T00:00:00Z',
    published_by = '22000000-0000-0000-0000-000000000001'
WHERE workflow_version_id = '32100000-0000-0000-0000-000000000001'
  AND version_status = 'DRAFT';

INSERT INTO config.routing_rule(
    routing_rule_id, tenant_id, project_id, rule_name, rule_priority,
    condition_json, assignment_group_id, assignment_method
) VALUES
('36000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','Accounts Payable module',10,'{"all":[{"field":"module_code","operator":"equals","value":"ACCOUNTS_PAYABLE"}]}','23000000-0000-0000-0000-000000000002','ROUND_ROBIN'),
('36000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','ERP default route',9999,'{}','23000000-0000-0000-0000-000000000001','GROUP_ONLY')
ON CONFLICT (routing_rule_id) DO NOTHING;

INSERT INTO config.routing_rule_version(
    routing_rule_version_id,routing_rule_id,version_number,version_status,
    rule_priority,condition_json,assignment_group_id,assignment_method,
    effective_from,created_by,approved_by,approved_at,change_reason
) VALUES
('36100000-0000-0000-0000-000000000001','36000000-0000-0000-0000-000000000001',1,'DRAFT',10,'{"all":[{"field":"module_code","operator":"equals","value":"ACCOUNTS_PAYABLE"}]}','23000000-0000-0000-0000-000000000002','ROUND_ROBIN','2025-01-01T00:00:00Z','22000000-0000-0000-0000-000000000001','22000000-0000-0000-0000-000000000001','2025-01-01T00:00:00Z','Initial AP route'),
('36100000-0000-0000-0000-000000000002','36000000-0000-0000-0000-000000000002',1,'DRAFT',9999,'{}','23000000-0000-0000-0000-000000000001','GROUP_ONLY','2025-01-01T00:00:00Z','22000000-0000-0000-0000-000000000001','22000000-0000-0000-0000-000000000001','2025-01-01T00:00:00Z','Explicit ERP fallback')
ON CONFLICT (routing_rule_version_id) DO NOTHING;

UPDATE config.routing_rule_version
SET version_status='PUBLISHED',published_at='2025-01-01T00:00:00Z'
WHERE routing_rule_version_id IN (
    '36100000-0000-0000-0000-000000000001',
    '36100000-0000-0000-0000-000000000002'
) AND version_status='DRAFT';

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

INSERT INTO config.queue_definition(
    queue_id,tenant_id,project_id,queue_name,description,filter_json,sort_json,
    columns_json,visibility_type,owner_group_id,display_order
) VALUES
('37000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','Unassigned','ERP tickets awaiting a support group','{"field":"assignment_group_id","operator":"is_null"}','[{"field":"created_at","direction":"DESC"}]','["ticket_key","summary","priority","status","created_at"]','ALL_AGENTS',NULL,10),
('37000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','Assigned to me','ERP tickets assigned to the current analyst','{"field":"assignee_user_id","operator":"equals_context","value":"user_id"}','[{"field":"created_at","direction":"DESC"}]','["ticket_key","summary","priority","status","assignment_group","created_at"]','ALL_AGENTS',NULL,20),
('37000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','Fusion AP group','ERP tickets assigned to Fusion AP support','{"field":"assignment_group_id","operator":"equals","value":"23000000-0000-0000-0000-000000000002"}','[{"field":"created_at","direction":"DESC"}]','["ticket_key","summary","priority","status","assignee","created_at"]','GROUP','23000000-0000-0000-0000-000000000002',30),
('37000000-0000-0000-0000-000000000004','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','ERP project','All authorized ERP tickets','{}','[{"field":"created_at","direction":"DESC"}]','["ticket_key","summary","priority","status","assignment_group","assignee","created_at"]','PROJECT_AGENTS',NULL,40)
ON CONFLICT (queue_id) DO NOTHING;

INSERT INTO config.queue_definition_version(
    queue_definition_version_id,queue_id,version_number,version_status,
    filter_json,sort_json,columns_json,visibility_type,owner_group_id,
    effective_from,created_by,approved_by,approved_at,change_reason
) SELECT
    ('37100000-0000-0000-0000-' || right(queue.queue_id::text,12))::uuid,
    queue.queue_id,1,'DRAFT',queue.filter_json,queue.sort_json,queue.columns_json,
    queue.visibility_type,queue.owner_group_id,'2025-01-01T00:00:00Z',
    '22000000-0000-0000-0000-000000000001',
    '22000000-0000-0000-0000-000000000001','2025-01-01T00:00:00Z',
    'Initial deterministic analyst queue'
FROM config.queue_definition AS queue
WHERE queue.queue_id BETWEEN
    '37000000-0000-0000-0000-000000000001' AND
    '37000000-0000-0000-0000-000000000004'
ON CONFLICT (queue_definition_version_id) DO NOTHING;

UPDATE config.queue_definition_version
SET version_status='PUBLISHED',published_at='2025-01-01T00:00:00Z'
WHERE queue_definition_version_id BETWEEN
    '37100000-0000-0000-0000-000000000001' AND
    '37100000-0000-0000-0000-000000000004'
  AND version_status='DRAFT';

-- Development-only immutable business calendar and initial SLA goals. These
-- are deliberately absent from the production baseline installer.
INSERT INTO config.business_calendar(
    calendar_id,tenant_id,calendar_code,calendar_name,timezone_name
) VALUES (
    '38000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'UK_BUSINESS_HOURS','UK Business Hours','Europe/London'
) ON CONFLICT (calendar_id) DO NOTHING;

INSERT INTO config.business_calendar_version(
    business_calendar_version_id,calendar_id,version_number,version_status,
    timezone_name,twenty_four_seven_flag,schedule_json,effective_from,
    created_by,approved_by,approved_at,change_reason
) VALUES (
    '38100000-0000-0000-0000-000000000001',
    '38000000-0000-0000-0000-000000000001',1,'DRAFT','Europe/London',false,
    '{"working_days":[1,2,3,4,5]}','2025-01-01T00:00:00Z',
    '22000000-0000-0000-0000-000000000001',
    '22000000-0000-0000-0000-000000000001','2025-01-01T00:00:00Z',
    'Initial development business calendar'
) ON CONFLICT (business_calendar_version_id) DO NOTHING;

INSERT INTO config.calendar_working_period(
    business_calendar_version_id,iso_day_of_week,start_local_time,end_local_time
)
SELECT '38100000-0000-0000-0000-000000000001',day_number,'09:00','17:00'
FROM generate_series(1,5) AS day_number
ON CONFLICT (
    business_calendar_version_id,iso_day_of_week,start_local_time,end_local_time
) DO NOTHING;

INSERT INTO config.calendar_exception(
    business_calendar_version_id,exception_date,exception_type,description
) VALUES (
    '38100000-0000-0000-0000-000000000001','2026-12-25','CLOSED','Christmas Day'
) ON CONFLICT (business_calendar_version_id,exception_date) DO NOTHING;

INSERT INTO config.sla_definition(
    sla_definition_id,tenant_id,project_id,sla_code,sla_name,metric_code,
    start_condition_json,pause_condition_json,stop_condition_json
) VALUES
('38200000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','FIRST_RESPONSE','Time to first response','TIME_TO_FIRST_RESPONSE','{"event":"TICKET_CREATED"}','[]','{"field":"first_response_at","operator":"is_not_null"}'),
('38200000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','RESOLUTION','Time to resolution','TIME_TO_RESOLUTION','{"event":"TICKET_CREATED"}','[{"status_code":"WAITING_FOR_CUSTOMER"}]','{"status_category":"DONE"}')
ON CONFLICT (sla_definition_id) DO NOTHING;

INSERT INTO config.sla_definition_version(
    sla_definition_version_id,sla_definition_id,version_number,version_status,
    metric_code,start_condition_json,pause_condition_json,stop_condition_json,
    effective_from,created_by,approved_by,approved_at,change_reason
) VALUES
('38300000-0000-0000-0000-000000000001','38200000-0000-0000-0000-000000000001',1,'DRAFT','TIME_TO_FIRST_RESPONSE','{"event":"TICKET_CREATED"}','[]','{"field":"first_response_at","operator":"is_not_null"}','2025-01-01T00:00:00Z','22000000-0000-0000-0000-000000000001','22000000-0000-0000-0000-000000000001','2025-01-01T00:00:00Z','Initial first-response SLA'),
('38300000-0000-0000-0000-000000000002','38200000-0000-0000-0000-000000000002',1,'DRAFT','TIME_TO_RESOLUTION','{"event":"TICKET_CREATED"}','[{"status_code":"WAITING_FOR_CUSTOMER"}]','{"status_category":"DONE"}','2025-01-01T00:00:00Z','22000000-0000-0000-0000-000000000001','22000000-0000-0000-0000-000000000001','2025-01-01T00:00:00Z','Initial resolution SLA')
ON CONFLICT (sla_definition_version_id) DO NOTHING;

INSERT INTO config.sla_goal(
    sla_goal_id,sla_definition_id,goal_name,match_condition_json,target_minutes,
    warning_minutes,calendar_id,priority_order
) VALUES
('38400000-0000-0000-0000-000000000001','38200000-0000-0000-0000-000000000001','P1 first response','{"priority_code":"P1"}',15,5,'38000000-0000-0000-0000-000000000001',10),
('38400000-0000-0000-0000-000000000002','38200000-0000-0000-0000-000000000001','Default first response','{}',240,60,'38000000-0000-0000-0000-000000000001',999),
('38400000-0000-0000-0000-000000000003','38200000-0000-0000-0000-000000000002','P1 resolution','{"priority_code":"P1"}',240,60,'38000000-0000-0000-0000-000000000001',10),
('38400000-0000-0000-0000-000000000004','38200000-0000-0000-0000-000000000002','Default resolution','{}',2400,480,'38000000-0000-0000-0000-000000000001',999)
ON CONFLICT (sla_goal_id) DO NOTHING;

INSERT INTO config.sla_goal_version(
    sla_goal_version_id,sla_goal_id,sla_definition_version_id,
    business_calendar_version_id,version_number,version_status,
    match_condition_json,target_minutes,warning_minutes,priority_order,
    effective_from,created_by,approved_by,approved_at,change_reason
)
SELECT
    ('38500000-0000-0000-0000-' || right(goal.sla_goal_id::text,12))::uuid,
    goal.sla_goal_id,
    CASE goal.sla_definition_id
      WHEN '38200000-0000-0000-0000-000000000001'
        THEN '38300000-0000-0000-0000-000000000001'::uuid
      ELSE '38300000-0000-0000-0000-000000000002'::uuid
    END,
    '38100000-0000-0000-0000-000000000001',1,'DRAFT',
    goal.match_condition_json,goal.target_minutes,goal.warning_minutes,
    goal.priority_order,'2025-01-01T00:00:00Z',
    '22000000-0000-0000-0000-000000000001',
    '22000000-0000-0000-0000-000000000001','2025-01-01T00:00:00Z',
    'Initial development SLA goal'
FROM config.sla_goal AS goal
WHERE goal.sla_goal_id BETWEEN
    '38400000-0000-0000-0000-000000000001' AND
    '38400000-0000-0000-0000-000000000004'
ON CONFLICT (sla_goal_version_id) DO NOTHING;

UPDATE config.business_calendar_version
SET version_status='PUBLISHED',published_at='2025-01-01T00:00:00Z'
WHERE business_calendar_version_id='38100000-0000-0000-0000-000000000001'
  AND version_status='DRAFT';

UPDATE config.sla_definition_version
SET version_status='PUBLISHED',published_at='2025-01-01T00:00:00Z'
WHERE sla_definition_version_id BETWEEN
    '38300000-0000-0000-0000-000000000001' AND
    '38300000-0000-0000-0000-000000000002'
  AND version_status='DRAFT';

UPDATE config.sla_goal_version
SET version_status='PUBLISHED',published_at='2025-01-01T00:00:00Z'
WHERE sla_goal_version_id IN (
    '38500000-0000-0000-0000-000000000001',
    '38500000-0000-0000-0000-000000000002',
    '38500000-0000-0000-0000-000000000003',
    '38500000-0000-0000-0000-000000000004'
) AND version_status='DRAFT';

-- Development-only, non-sensitive notification templates. Variables are
-- deliberately limited to identifiers, display labels, and portal links.
WITH template_codes(ordinal,base_code) AS (VALUES
    (1,'TICKET_CREATED'),(2,'TICKET_ASSIGNED'),(3,'PUBLIC_COMMENT_ADDED'),
    (4,'STATUS_CHANGED'),(5,'APPROVAL_REQUESTED'),(6,'APPROVAL_DECIDED'),
    (7,'SLA_WARNING'),(8,'SLA_BREACHED'),(9,'TICKET_RESOLVED'),
    (10,'TICKET_CLOSED')
), channels(channel_ordinal,channel_code) AS (VALUES (0,'EMAIL'),(1,'PORTAL'))
INSERT INTO config.notification_template(
    notification_template_id,tenant_id,template_code,template_name
)
SELECT
    ('38800000-0000-0000-0000-' ||
      lpad(((ordinal-1)*2+channel_ordinal+1)::text,12,'0'))::uuid,
    '20000000-0000-0000-0000-000000000001',
    base_code || '_' || channel_code,
    initcap(replace(base_code,'_',' ')) || ' ' || lower(channel_code)
FROM template_codes CROSS JOIN channels
ON CONFLICT (notification_template_id) DO NOTHING;

INSERT INTO config.notification_template_version(
    notification_template_version_id,notification_template_id,version_number,
    version_status,channel_code,subject_template,body_template,content_type,
    effective_from,created_by,approved_by,approved_at,change_reason
)
SELECT
    ('38900000-0000-0000-0000-' || right(template.notification_template_id::text,12))::uuid,
    template.notification_template_id,1,'DRAFT',
    CASE WHEN template.template_code LIKE '%_EMAIL' THEN 'EMAIL' ELSE 'PORTAL' END,
    '{{ event_name }}: {{ ticket_key }}',
    '{{ event_name }} for {{ ticket_key }}. Open {{ action_url }}.',
    'TEXT','2025-01-01T00:00:00Z',
    '22000000-0000-0000-0000-000000000001',
    '22000000-0000-0000-0000-000000000001','2025-01-01T00:00:00Z',
    'Initial safe notification template'
FROM config.notification_template AS template
WHERE template.notification_template_id BETWEEN
  '38800000-0000-0000-0000-000000000001' AND
  '38800000-0000-0000-0000-000000000020'
ON CONFLICT (notification_template_version_id) DO NOTHING;

UPDATE config.notification_template_version
SET version_status='PUBLISHED',published_at='2025-01-01T00:00:00Z'
WHERE notification_template_version_id BETWEEN
  '38900000-0000-0000-0000-000000000001' AND
  '38900000-0000-0000-0000-000000000020'
  AND version_status='DRAFT';

COMMIT;
