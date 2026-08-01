\set ON_ERROR_STOP on

-- Optional demo configuration. Do not use these identities in production.
BEGIN;

INSERT INTO identity.tenant(
    tenant_id, tenant_code, tenant_name, default_timezone
) VALUES (
    '10000000-0000-0000-0000-000000000001',
    'DEMO','Fusion Helpdesk Demo','Europe/London'
) ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO identity.business_unit(
    business_unit_id, tenant_id, business_unit_code, business_unit_name
) VALUES (
    '11000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'CORP','Corporate Services'
) ON CONFLICT (business_unit_id) DO NOTHING;

INSERT INTO identity.app_user(
    user_id, tenant_id, external_subject, email_address, display_name,
    employee_number, business_unit_id, timezone_name
) VALUES
(
    '12000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'demo-admin','admin@example.invalid','Demo Administrator','ADM001',
    '11000000-0000-0000-0000-000000000001','Europe/London'
),
(
    '12000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    'demo-employee','employee@example.invalid','Demo Employee','EMP001',
    '11000000-0000-0000-0000-000000000001','Europe/London'
),
(
    '12000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000001',
    'demo-analyst','analyst@example.invalid','Demo Analyst','ANL001',
    '11000000-0000-0000-0000-000000000001','Europe/London'
)
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO identity.user_role(tenant_id, user_id, role_code, granted_by) VALUES
('10000000-0000-0000-0000-000000000001','12000000-0000-0000-0000-000000000001','PLATFORM_ADMIN','12000000-0000-0000-0000-000000000001'),
('10000000-0000-0000-0000-000000000001','12000000-0000-0000-0000-000000000002','CUSTOMER','12000000-0000-0000-0000-000000000001'),
('10000000-0000-0000-0000-000000000001','12000000-0000-0000-0000-000000000003','AGENT','12000000-0000-0000-0000-000000000001')
ON CONFLICT DO NOTHING;

INSERT INTO identity.support_group(
    support_group_id, tenant_id, group_code, group_name, assignment_method
) VALUES
('13000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','IT_TRIAGE','IT Service Desk Triage','ROUND_ROBIN'),
('13000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','BI_SUPPORT','Oracle Analytics Support','LEAST_WEIGHTED_WORKLOAD'),
('13000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','ERP_AP_SUPPORT','ERP Accounts Payable Support','LEAST_OPEN_TICKETS')
ON CONFLICT (support_group_id) DO NOTHING;

INSERT INTO identity.support_group_member(
    support_group_id, user_id, member_role, capacity_points
) VALUES
('13000000-0000-0000-0000-000000000001','12000000-0000-0000-0000-000000000003','AGENT',10),
('13000000-0000-0000-0000-000000000002','12000000-0000-0000-0000-000000000003','LEAD',10),
('13000000-0000-0000-0000-000000000003','12000000-0000-0000-0000-000000000003','AGENT',10)
ON CONFLICT DO NOTHING;


INSERT INTO kb.source(
    source_id, tenant_id, source_code, source_name, source_type,
    publisher_name, acquisition_method, automated_access_allowed,
    permission_reference
) VALUES
('13100000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','COMPANY_POLICY','Company Policies','COMPANY_POLICY','Demo Company','MANUAL_UPLOAD',false,'Company policy owner approval required'),
('13100000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','COMPANY_PROCEDURE','Company Procedures','COMPANY_PROCEDURE','Demo Company','MANUAL_UPLOAD',false,'Process owner approval required'),
('13100000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','INTERNAL_KNOWLEDGE','Internal Knowledge Articles','INTERNAL_KNOWLEDGE','Demo Company','REPOSITORY_CONNECTOR',false,'Knowledge governance approval required'),
('13100000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000001','HISTORICAL_RESOLUTION','Validated Historical Resolutions','HISTORICAL_RESOLUTION','Demo Company','TICKET_PUBLICATION',false,'Only validated and sanitized resolutions may be published')
ON CONFLICT (source_id) DO NOTHING;

INSERT INTO config.service_project(
    project_id, tenant_id, project_key, project_name, default_group_id, default_timezone
) VALUES (
    '14000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'IT','Corporate IT Helpdesk',
    '13000000-0000-0000-0000-000000000001','Europe/London'
) ON CONFLICT (project_id) DO NOTHING;

INSERT INTO config.service_node(
    service_node_id, tenant_id, parent_node_id, node_code, node_name, node_type, owner_group_id, display_order
) VALUES
('15000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',NULL,'ORACLE_FUSION','Oracle Fusion Cloud Applications','SERVICE_FAMILY','13000000-0000-0000-0000-000000000001',10),
('15000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','15000000-0000-0000-0000-000000000001','FINANCIALS','Financials','SERVICE','13000000-0000-0000-0000-000000000003',20),
('15000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','15000000-0000-0000-0000-000000000002','ACCOUNTS_PAYABLE','Accounts Payable','MODULE','13000000-0000-0000-0000-000000000003',30),
('15000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000001',NULL,'ANALYTICS','Analytics and Reporting','SERVICE_FAMILY','13000000-0000-0000-0000-000000000002',40),
('15000000-0000-0000-0000-000000000005','10000000-0000-0000-0000-000000000001','15000000-0000-0000-0000-000000000004','OAC','Oracle Analytics Cloud','MODULE','13000000-0000-0000-0000-000000000002',50),
('15000000-0000-0000-0000-000000000006','10000000-0000-0000-0000-000000000001','15000000-0000-0000-0000-000000000004','OTBI','OTBI','MODULE','13000000-0000-0000-0000-000000000002',60),
('15000000-0000-0000-0000-000000000007','10000000-0000-0000-0000-000000000001','15000000-0000-0000-0000-000000000004','BI_PUBLISHER','BI Publisher','MODULE','13000000-0000-0000-0000-000000000002',70),
('15000000-0000-0000-0000-000000000008','10000000-0000-0000-0000-000000000001','15000000-0000-0000-0000-000000000004','FDI','Fusion Data Intelligence','MODULE','13000000-0000-0000-0000-000000000002',80)
ON CONFLICT (service_node_id) DO NOTHING;

INSERT INTO config.category(
    category_id, tenant_id, category_code, category_name
) VALUES
('16000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','APPLICATION_ERROR','Application Error'),
('16000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','ACCESS','Access and Security'),
('16000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','REPORTING','Reporting and Analytics'),
('16000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000001','DATA_ISSUE','Data Issue')
ON CONFLICT (category_id) DO NOTHING;

INSERT INTO config.workflow(
    workflow_id, tenant_id, workflow_code, workflow_name
) VALUES
('17000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','INCIDENT_STANDARD','Standard Incident Workflow'),
('17000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','SERVICE_REQUEST_STANDARD','Standard Service Request Workflow')
ON CONFLICT (workflow_id) DO NOTHING;

INSERT INTO config.workflow_version(
    workflow_version_id, workflow_id, version_number, version_status, effective_from, published_at, published_by
) VALUES
('17100000-0000-0000-0000-000000000001','17000000-0000-0000-0000-000000000001',1,'PUBLISHED',now(),now(),'12000000-0000-0000-0000-000000000001'),
('17100000-0000-0000-0000-000000000002','17000000-0000-0000-0000-000000000002',1,'PUBLISHED',now(),now(),'12000000-0000-0000-0000-000000000001')
ON CONFLICT (workflow_version_id) DO NOTHING;

INSERT INTO config.workflow_status(
    status_id, workflow_version_id, status_code, status_name, status_category,
    initial_flag, terminal_flag, customer_visible_name, display_order
) VALUES
('17200000-0000-0000-0000-000000000001','17100000-0000-0000-0000-000000000001','NEW','New','TO_DO',true,false,'Submitted',10),
('17200000-0000-0000-0000-000000000002','17100000-0000-0000-0000-000000000001','TRIAGE','Triage','IN_PROGRESS',false,false,'Under Review',20),
('17200000-0000-0000-0000-000000000003','17100000-0000-0000-0000-000000000001','IN_PROGRESS','In Progress','IN_PROGRESS',false,false,'In Progress',30),
('17200000-0000-0000-0000-000000000004','17100000-0000-0000-0000-000000000001','WAITING_CUSTOMER','Waiting for Customer','WAITING',false,false,'Waiting for You',40),
('17200000-0000-0000-0000-000000000005','17100000-0000-0000-0000-000000000001','RESOLVED','Resolved','DONE',false,false,'Resolved',50),
('17200000-0000-0000-0000-000000000006','17100000-0000-0000-0000-000000000001','CLOSED','Closed','DONE',false,true,'Closed',60),
('17300000-0000-0000-0000-000000000001','17100000-0000-0000-0000-000000000002','SUBMITTED','Submitted','TO_DO',true,false,'Submitted',10),
('17300000-0000-0000-0000-000000000002','17100000-0000-0000-0000-000000000002','IN_FULFILMENT','In Fulfilment','IN_PROGRESS',false,false,'In Progress',20),
('17300000-0000-0000-0000-000000000003','17100000-0000-0000-0000-000000000002','COMPLETED','Completed','DONE',false,false,'Completed',30),
('17300000-0000-0000-0000-000000000004','17100000-0000-0000-0000-000000000002','CLOSED','Closed','DONE',false,true,'Closed',40)
ON CONFLICT (status_id) DO NOTHING;

INSERT INTO config.workflow_transition(
    transition_id, workflow_version_id, transition_code, transition_name,
    from_status_id, to_status_id, validator_json, action_json, display_order
) VALUES
('17400000-0000-0000-0000-000000000001','17100000-0000-0000-0000-000000000001','START_TRIAGE','Start Triage','17200000-0000-0000-0000-000000000001','17200000-0000-0000-0000-000000000002','[]','[]',10),
('17400000-0000-0000-0000-000000000002','17100000-0000-0000-0000-000000000001','START_PROGRESS','Start Progress','17200000-0000-0000-0000-000000000002','17200000-0000-0000-0000-000000000003','[]','[]',20),
('17400000-0000-0000-0000-000000000003','17100000-0000-0000-0000-000000000001','WAIT_CUSTOMER','Wait for Customer','17200000-0000-0000-0000-000000000003','17200000-0000-0000-0000-000000000004','[]','[]',30),
('17400000-0000-0000-0000-000000000004','17100000-0000-0000-0000-000000000001','CUSTOMER_REPLIED','Customer Replied','17200000-0000-0000-0000-000000000004','17200000-0000-0000-0000-000000000003','[]','[]',40),
('17400000-0000-0000-0000-000000000005','17100000-0000-0000-0000-000000000001','RESOLVE','Resolve','17200000-0000-0000-0000-000000000003','17200000-0000-0000-0000-000000000005','[{"type":"required_field","field":"resolution_code"},{"type":"required_field","field":"resolution_summary"}]','[{"type":"set_timestamp","field":"resolved_at"}]',50),
('17400000-0000-0000-0000-000000000006','17100000-0000-0000-0000-000000000001','CLOSE','Close','17200000-0000-0000-0000-000000000005','17200000-0000-0000-0000-000000000006','[]','[{"type":"set_timestamp","field":"closed_at"}]',60),
('17500000-0000-0000-0000-000000000001','17100000-0000-0000-0000-000000000002','START_FULFILMENT','Start Fulfilment','17300000-0000-0000-0000-000000000001','17300000-0000-0000-0000-000000000002','[]','[]',10),
('17500000-0000-0000-0000-000000000002','17100000-0000-0000-0000-000000000002','COMPLETE','Complete','17300000-0000-0000-0000-000000000002','17300000-0000-0000-0000-000000000003','[]','[{"type":"set_timestamp","field":"resolved_at"}]',20),
('17500000-0000-0000-0000-000000000003','17100000-0000-0000-0000-000000000002','CLOSE','Close','17300000-0000-0000-0000-000000000003','17300000-0000-0000-0000-000000000004','[]','[{"type":"set_timestamp","field":"closed_at"}]',30)
ON CONFLICT (transition_id) DO NOTHING;

INSERT INTO config.request_type(
    request_type_id, tenant_id, project_id, work_type_id, workflow_id,
    request_type_code, request_type_name, portal_description, portal_group, display_order
)
SELECT
    x.request_type_id,
    '10000000-0000-0000-0000-000000000001',
    '14000000-0000-0000-0000-000000000001',
    wt.work_type_id,
    x.workflow_id,
    x.request_type_code,
    x.request_type_name,
    x.portal_description,
    x.portal_group,
    x.display_order
FROM (VALUES
    ('18000000-0000-0000-0000-000000000001'::uuid,'INCIDENT','17000000-0000-0000-0000-000000000001'::uuid,'REPORT_APPLICATION_ISSUE','Report an application issue','Something is not working as expected.','Get Help',10),
    ('18000000-0000-0000-0000-000000000002'::uuid,'INCIDENT','17000000-0000-0000-0000-000000000001'::uuid,'REPORT_DATA_ISSUE','Report incorrect report data','Report incorrect or missing analytics data.','Analytics',20),
    ('18000000-0000-0000-0000-000000000003'::uuid,'SERVICE_REQUEST','17000000-0000-0000-0000-000000000002'::uuid,'REQUEST_NEW_REPORT','Request a new report','Request a new OTBI, BI Publisher, OAC, or FDI report.','Analytics',30)
) AS x(request_type_id,work_type_code,workflow_id,request_type_code,request_type_name,portal_description,portal_group,display_order)
JOIN config.work_type wt
  ON wt.work_type_code = x.work_type_code AND wt.tenant_id IS NULL
ON CONFLICT (request_type_id) DO NOTHING;

INSERT INTO config.request_type_version(
    request_type_version_id, request_type_id, version_number, version_status,
    form_schema_json, effective_from, created_by, approved_by, approved_at,
    change_reason, published_at
) VALUES
('18100000-0000-0000-0000-000000000001','18000000-0000-0000-0000-000000000001',1,'PUBLISHED','{}',now(),'12000000-0000-0000-0000-000000000001','12000000-0000-0000-0000-000000000001',now(),'Initial demo form',now()),
('18100000-0000-0000-0000-000000000002','18000000-0000-0000-0000-000000000002',1,'PUBLISHED','{}',now(),'12000000-0000-0000-0000-000000000001','12000000-0000-0000-0000-000000000001',now(),'Initial demo form',now()),
('18100000-0000-0000-0000-000000000003','18000000-0000-0000-0000-000000000003',1,'PUBLISHED','{}',now(),'12000000-0000-0000-0000-000000000001','12000000-0000-0000-0000-000000000001',now(),'Initial demo form',now())
ON CONFLICT (request_type_version_id) DO NOTHING;

INSERT INTO config.routing_rule(
    routing_rule_id, tenant_id, project_id, rule_name, rule_priority,
    condition_json, assignment_group_id, assignment_method
) VALUES
('19000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','14000000-0000-0000-0000-000000000001','Route Analytics Modules',10,
 '{"any":[{"field":"service_node_code","operator":"in","value":["OAC","OTBI","BI_PUBLISHER","FDI"]}]}'::jsonb,
 '13000000-0000-0000-0000-000000000002','LEAST_WEIGHTED_WORKLOAD'),
('19000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','14000000-0000-0000-0000-000000000001','Route Accounts Payable',20,
 '{"all":[{"field":"service_node_code","operator":"equals","value":"ACCOUNTS_PAYABLE"}]}'::jsonb,
 '13000000-0000-0000-0000-000000000003','LEAST_OPEN_TICKETS'),
('19000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','14000000-0000-0000-0000-000000000001','Fallback to Triage',9999,
 '{}'::jsonb,
 '13000000-0000-0000-0000-000000000001','ROUND_ROBIN')
ON CONFLICT (routing_rule_id) DO NOTHING;

INSERT INTO config.routing_rule_version(
    routing_rule_version_id, routing_rule_id, version_number, version_status,
    rule_priority, condition_json, assignment_group_id, assignment_method,
    assignee_user_id, effective_from, created_by, approved_by, approved_at,
    change_reason, published_at
)
SELECT
    ('19110000-0000-0000-0000-' || right(replace(r.routing_rule_id::text, '-', ''), 12))::uuid,
    r.routing_rule_id, 1, 'PUBLISHED', r.rule_priority, r.condition_json,
    r.assignment_group_id, r.assignment_method, r.assignee_user_id, now(),
    '12000000-0000-0000-0000-000000000001',
    '12000000-0000-0000-0000-000000000001', now(),
    'Initial demo routing rule', now()
FROM config.routing_rule r
WHERE r.tenant_id = '10000000-0000-0000-0000-000000000001'
ON CONFLICT (routing_rule_version_id) DO NOTHING;

INSERT INTO config.queue_definition(
    queue_id, tenant_id, project_id, queue_name, description,
    filter_json, sort_json, columns_json, visibility_type, display_order
) VALUES
('19100000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','14000000-0000-0000-0000-000000000001','Unassigned','Tickets awaiting assignment',
 '{"all":[{"field":"assignment_group_id","operator":"is_null"}]}'::jsonb,
 '[{"field":"priority_rank","direction":"asc"},{"field":"created_at","direction":"asc"}]'::jsonb,
 '["ticket_key","summary","priority_code","created_at"]'::jsonb,'PROJECT_AGENTS',10),
('19100000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','14000000-0000-0000-0000-000000000001','Approaching SLA','Open tickets close to SLA breach',
 '{"all":[{"field":"status_category","operator":"not_in","value":["DONE","CANCELLED"]},{"field":"next_sla_minutes","operator":"less_than","value":120}]}'::jsonb,
 '[{"field":"next_sla_target","direction":"asc"}]'::jsonb,
 '["ticket_key","summary","assignment_group_name","priority_code","next_sla_target"]'::jsonb,'PROJECT_AGENTS',20)
ON CONFLICT (queue_id) DO NOTHING;

INSERT INTO config.queue_definition_version(
    queue_definition_version_id, queue_id, version_number, version_status,
    filter_json, sort_json, columns_json, visibility_type, owner_group_id,
    effective_from, created_by, approved_by, approved_at, change_reason, published_at
)
SELECT
    ('19110000-0000-0000-0001-' || right(replace(q.queue_id::text, '-', ''), 12))::uuid,
    q.queue_id, 1, 'PUBLISHED', q.filter_json, q.sort_json, q.columns_json,
    q.visibility_type, q.owner_group_id, now(),
    '12000000-0000-0000-0000-000000000001',
    '12000000-0000-0000-0000-000000000001', now(),
    'Initial demo queue', now()
FROM config.queue_definition q
WHERE q.tenant_id = '10000000-0000-0000-0000-000000000001'
ON CONFLICT (queue_definition_version_id) DO NOTHING;

INSERT INTO config.business_calendar(
    calendar_id, tenant_id, calendar_code, calendar_name, timezone_name
) VALUES (
    '19200000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'UK_BUSINESS_HOURS','UK Business Hours','Europe/London'
) ON CONFLICT (calendar_id) DO NOTHING;

INSERT INTO config.business_calendar_version(
    business_calendar_version_id, calendar_id, version_number, version_status,
    timezone_name, twenty_four_seven_flag, schedule_json, effective_from,
    created_by, approved_by, approved_at, change_reason, published_at
) VALUES (
    '19210000-0000-0000-0000-000000000001',
    '19200000-0000-0000-0000-000000000001', 1, 'PUBLISHED',
    'Europe/London', false, '{}', now(),
    '12000000-0000-0000-0000-000000000001',
    '12000000-0000-0000-0000-000000000001', now(),
    'Initial demo calendar', now()
) ON CONFLICT (business_calendar_version_id) DO NOTHING;

INSERT INTO config.calendar_working_period(
    working_period_id, business_calendar_version_id,
    iso_day_of_week, start_local_time, end_local_time
)
SELECT gen_random_uuid(), '19210000-0000-0000-0000-000000000001', d, '09:00'::time, '17:30'::time
FROM generate_series(1,5) d
WHERE NOT EXISTS (
    SELECT 1 FROM config.calendar_working_period c
    WHERE c.business_calendar_version_id = '19210000-0000-0000-0000-000000000001'
      AND c.iso_day_of_week = d
);

INSERT INTO config.sla_definition(
    sla_definition_id, tenant_id, project_id, sla_code, sla_name,
    metric_code, start_condition_json, pause_condition_json, stop_condition_json
) VALUES
('19300000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','14000000-0000-0000-0000-000000000001','FIRST_RESPONSE','Time to First Response','TIME_TO_FIRST_RESPONSE','{"event":"TICKET_CREATED"}','[]','{"field":"first_response_at","operator":"is_not_null"}'),
('19300000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','14000000-0000-0000-0000-000000000001','RESOLUTION','Time to Resolution','TIME_TO_RESOLUTION','{"event":"TICKET_CREATED"}','[{"status_code":"WAITING_CUSTOMER"}]','{"status_category":"DONE"}')
ON CONFLICT (sla_definition_id) DO NOTHING;

INSERT INTO config.sla_definition_version(
    sla_definition_version_id, sla_definition_id, version_number, version_status,
    metric_code, start_condition_json, pause_condition_json, stop_condition_json,
    effective_from, created_by, approved_by, approved_at, change_reason, published_at
)
SELECT
    CASE d.sla_definition_id
        WHEN '19300000-0000-0000-0000-000000000001' THEN '19310000-0000-0000-0000-000000000001'::uuid
        ELSE '19310000-0000-0000-0000-000000000002'::uuid
    END,
    d.sla_definition_id, 1, 'PUBLISHED', d.metric_code,
    d.start_condition_json, d.pause_condition_json, d.stop_condition_json,
    now(), '12000000-0000-0000-0000-000000000001',
    '12000000-0000-0000-0000-000000000001', now(),
    'Initial demo SLA definition', now()
FROM config.sla_definition d
WHERE d.tenant_id = '10000000-0000-0000-0000-000000000001'
ON CONFLICT (sla_definition_version_id) DO NOTHING;

INSERT INTO config.sla_goal(
    sla_goal_id, sla_definition_id, goal_name, match_condition_json,
    target_minutes, warning_minutes, calendar_id, priority_order
) VALUES
('19400000-0000-0000-0000-000000000001','19300000-0000-0000-0000-000000000001','P1 First Response','{"priority_code":"P1"}',15,5,'19200000-0000-0000-0000-000000000001',10),
('19400000-0000-0000-0000-000000000002','19300000-0000-0000-0000-000000000001','Default First Response','{}',240,60,'19200000-0000-0000-0000-000000000001',999),
('19400000-0000-0000-0000-000000000003','19300000-0000-0000-0000-000000000002','P1 Resolution','{"priority_code":"P1"}',240,60,'19200000-0000-0000-0000-000000000001',10),
('19400000-0000-0000-0000-000000000004','19300000-0000-0000-0000-000000000002','Default Resolution','{}',2400,480,'19200000-0000-0000-0000-000000000001',999)
ON CONFLICT (sla_goal_id) DO NOTHING;

INSERT INTO config.sla_goal_version(
    sla_goal_version_id, sla_goal_id, sla_definition_version_id,
    business_calendar_version_id, version_number, version_status,
    match_condition_json, target_minutes, warning_minutes, priority_order,
    effective_from, created_by, approved_by, approved_at, change_reason, published_at
)
SELECT
    CASE g.sla_goal_id
        WHEN '19400000-0000-0000-0000-000000000001' THEN '19410000-0000-0000-0000-000000000001'::uuid
        WHEN '19400000-0000-0000-0000-000000000002' THEN '19410000-0000-0000-0000-000000000002'::uuid
        WHEN '19400000-0000-0000-0000-000000000003' THEN '19410000-0000-0000-0000-000000000003'::uuid
        ELSE '19410000-0000-0000-0000-000000000004'::uuid
    END,
    g.sla_goal_id,
    CASE g.sla_definition_id
        WHEN '19300000-0000-0000-0000-000000000001' THEN '19310000-0000-0000-0000-000000000001'::uuid
        ELSE '19310000-0000-0000-0000-000000000002'::uuid
    END,
    '19210000-0000-0000-0000-000000000001', 1, 'PUBLISHED',
    g.match_condition_json, g.target_minutes, g.warning_minutes, g.priority_order,
    now(), '12000000-0000-0000-0000-000000000001',
    '12000000-0000-0000-0000-000000000001', now(),
    'Initial demo SLA goal', now()
FROM config.sla_goal g
WHERE g.sla_definition_id IN (
    '19300000-0000-0000-0000-000000000001',
    '19300000-0000-0000-0000-000000000002'
)
ON CONFLICT (sla_goal_version_id) DO NOTHING;

COMMIT;
