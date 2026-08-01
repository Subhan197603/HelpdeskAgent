\set ON_ERROR_STOP on

BEGIN;

INSERT INTO identity.role_definition(role_code, role_name, description) VALUES
('PLATFORM_ADMIN','Platform Administrator','Full platform administration'),
('PROJECT_ADMIN','Service Project Administrator','Administers a service project'),
('SERVICE_OWNER','Service Owner','Owns a supported service'),
('SUPPORT_MANAGER','Support Manager','Manages queues and analysts'),
('AGENT','Support Analyst','Works and resolves tickets'),
('CUSTOMER','Customer','Raises and follows requests'),
('APPROVER','Approver','Approves workflow requests'),
('KNOWLEDGE_AUTHOR','Knowledge Author','Creates knowledge documents'),
('KNOWLEDGE_APPROVER','Knowledge Approver','Reviews and approves knowledge'),
('AUDITOR','Auditor','Reviews immutable audit data'),
('AI_ADMIN','AI Administrator','Administers agents and models'),
('REPORTING_USER','Reporting User','Consumes reports and dashboards')
ON CONFLICT (role_code) DO NOTHING;

INSERT INTO config.priority(priority_code, priority_name, rank_order, workload_weight) VALUES
('P1','Critical',1,5.0),
('P2','High',2,3.0),
('P3','Medium',3,2.0),
('P4','Low',4,1.0),
('P5','Planning',5,0.5)
ON CONFLICT (priority_code) DO NOTHING;

INSERT INTO config.impact(impact_code, impact_name, rank_order) VALUES
('EXTENSIVE', 'Enterprise or safety-critical impact', 1),
('SIGNIFICANT', 'Multiple teams or a critical business process', 2),
('MODERATE', 'One team or a non-critical business process', 3),
('LIMITED', 'Single user or low business impact', 4)
ON CONFLICT (impact_code) DO NOTHING;

INSERT INTO config.urgency(urgency_code, urgency_name, rank_order) VALUES
('IMMEDIATE', 'Work cannot continue', 1),
('HIGH', 'Material degradation with limited workaround', 2),
('NORMAL', 'Work can continue with a workaround', 3),
('LOW', 'Planning or convenience request', 4)
ON CONFLICT (urgency_code) DO NOTHING;

INSERT INTO config.priority_matrix(
    impact_code, urgency_code, priority_code, evaluation_order, approval_status
) VALUES
('EXTENSIVE', 'IMMEDIATE', 'P1', 100, 'APPROVED'),
('EXTENSIVE', 'HIGH', 'P1', 100, 'APPROVED'),
('EXTENSIVE', 'NORMAL', 'P2', 100, 'APPROVED'),
('EXTENSIVE', 'LOW', 'P3', 100, 'APPROVED'),
('SIGNIFICANT', 'IMMEDIATE', 'P1', 100, 'APPROVED'),
('SIGNIFICANT', 'HIGH', 'P2', 100, 'APPROVED'),
('SIGNIFICANT', 'NORMAL', 'P3', 100, 'APPROVED'),
('SIGNIFICANT', 'LOW', 'P4', 100, 'APPROVED'),
('MODERATE', 'IMMEDIATE', 'P2', 100, 'APPROVED'),
('MODERATE', 'HIGH', 'P3', 100, 'APPROVED'),
('MODERATE', 'NORMAL', 'P3', 100, 'APPROVED'),
('MODERATE', 'LOW', 'P4', 100, 'APPROVED'),
('LIMITED', 'IMMEDIATE', 'P3', 100, 'APPROVED'),
('LIMITED', 'HIGH', 'P3', 100, 'APPROVED'),
('LIMITED', 'NORMAL', 'P4', 100, 'APPROVED'),
('LIMITED', 'LOW', 'P5', 100, 'APPROVED')
ON CONFLICT DO NOTHING;

INSERT INTO config.channel(channel_code, channel_name) VALUES
('PORTAL','Employee Portal'),
('CHAT','AI Chat'),
('EMAIL','Email'),
('PHONE','Telephone'),
('API','API Integration'),
('MONITORING','Monitoring Event')
ON CONFLICT (channel_code) DO NOTHING;

INSERT INTO config.environment(environment_code, environment_name, production_flag) VALUES
('PROD','Production',true),
('TEST','Test',false),
('DEV','Development',false),
('TRAIN','Training',false),
('UNKNOWN','Not Known',false)
ON CONFLICT (environment_code) DO NOTHING;

INSERT INTO config.resolution_code(resolution_code, resolution_name) VALUES
('FIXED','Fixed'),
('WORKAROUND','Workaround Provided'),
('USER_EDUCATION','User Guidance Provided'),
('DUPLICATE','Duplicate'),
('NO_FAULT_FOUND','No Fault Found'),
('CONFIGURATION_CHANGE','Configuration Changed'),
('DATA_CORRECTION','Data Corrected'),
('KNOWN_ERROR','Known Error'),
('CANCELLED','Cancelled')
ON CONFLICT (resolution_code) DO NOTHING;

INSERT INTO itsm.ticket_link_type(link_type_code, outward_label, inward_label, symmetric_flag) VALUES
('DUPLICATES','duplicates','is duplicated by',false),
('RELATED_TO','relates to','relates to',true),
('CAUSED_BY','is caused by','causes',false),
('BLOCKS','blocks','is blocked by',false),
('RESOLVED_BY_CHANGE','is resolved by change','resolves',false),
('INCIDENT_OF_PROBLEM','is incident of problem','has incident',false),
('POST_INCIDENT_REVIEW_OF','reviews incident','has review',false),
('PARENT','is parent of','is child of',false)
ON CONFLICT (link_type_code) DO NOTHING;


INSERT INTO config.work_type(tenant_id, work_type_code, work_type_name, itsm_category) VALUES
(NULL,'SERVICE_REQUEST','Service Request','SERVICE_REQUEST'),
(NULL,'INCIDENT','Incident','INCIDENT'),
(NULL,'PROBLEM','Problem','PROBLEM'),
(NULL,'CHANGE','Change','CHANGE'),
(NULL,'ACCESS_REQUEST','Access Request','ACCESS_REQUEST'),
(NULL,'QUESTION','Question','QUESTION'),
(NULL,'TASK','Task','TASK'),
(NULL,'POST_INCIDENT_REVIEW','Post-Incident Review','POST_INCIDENT_REVIEW')
ON CONFLICT (tenant_id, work_type_code) DO NOTHING;

INSERT INTO kb.source(
    tenant_id, source_code, source_name, source_type, publisher_name,
    base_url, acquisition_method, automated_access_allowed,
    permission_reference, active_flag
) VALUES
(NULL,'ORACLE_PUBLIC_DOCS','Oracle Public Documentation',
 'ORACLE_PUBLIC_DOCUMENTATION','Oracle',
 'https://docs.oracle.com/en/cloud/saas/',
 'MANUAL_UPLOAD',false,
 'Automated acquisition requires separately recorded approval.',true),
(NULL,'ORACLE_FDI_DOCS','Oracle Fusion Data Intelligence Documentation',
 'ORACLE_PUBLIC_DOCUMENTATION','Oracle',
 'https://docs.oracle.com/en/cloud/saas/analytics/',
 'MANUAL_UPLOAD',false,
 'Automated acquisition requires separately recorded approval.',true)
ON CONFLICT (tenant_id, source_code) DO NOTHING;

INSERT INTO kb.release(release_family, release_code, release_name, support_status) VALUES
('FUSION_APPLICATIONS','26C','Oracle Fusion Cloud Applications 26C','CURRENT'),
('FUSION_DATA_INTELLIGENCE','26.R2','Oracle Fusion Data Intelligence 26.R2','CURRENT')
ON CONFLICT (release_family, release_code) DO NOTHING;

INSERT INTO config.application(
    application_id, application_code, application_name, release_family
) VALUES
('21000000-0000-0000-0000-000000000001', 'FUSION_APPLICATIONS',
 'Oracle Fusion Cloud Applications', 'FUSION_APPLICATIONS'),
('21000000-0000-0000-0000-000000000002', 'FUSION_DATA_INTELLIGENCE',
 'Oracle Fusion Data Intelligence', 'FUSION_DATA_INTELLIGENCE')
ON CONFLICT (application_id) DO NOTHING;

INSERT INTO config.product_release(
    product_release_id, application_id, release_family, release_code,
    release_name, release_status
) VALUES
('21100000-0000-0000-0000-000000000001',
 '21000000-0000-0000-0000-000000000001',
 'FUSION_APPLICATIONS', '26C', 'Oracle Fusion Cloud Applications 26C', 'CURRENT'),
('21100000-0000-0000-0000-000000000002',
 '21000000-0000-0000-0000-000000000002',
 'FUSION_DATA_INTELLIGENCE', '26.R2', 'Oracle Fusion Data Intelligence 26.R2', 'CURRENT')
ON CONFLICT (product_release_id) DO NOTHING;

INSERT INTO ai.feature_policy(
    feature_policy_id, scope_type, enabled_flag, approval_status
) VALUES (
    '21200000-0000-0000-0000-000000000001', 'GLOBAL', false, 'APPROVED'
) ON CONFLICT (feature_policy_id) DO NOTHING;

INSERT INTO kb.embedding_model(
    embedding_model_code, provider_name, model_name, vector_dimension, active_flag
) VALUES
('DEFAULT_1536','CONFIGURE_AT_DEPLOYMENT','Configure an approved 1536-dimensional embedding model',1536,true)
ON CONFLICT (embedding_model_code) DO NOTHING;

-- Global Oracle product hierarchy.
INSERT INTO kb.product_node(product_code, product_name, product_level, release_family, display_order) VALUES
('FUSION_APPLICATIONS','Oracle Fusion Cloud Applications','SUITE','FUSION_APPLICATIONS',10),
('FUSION_DATA_INTELLIGENCE','Oracle Fusion Data Intelligence','PRODUCT','FUSION_DATA_INTELLIGENCE',20)
ON CONFLICT (tenant_id, product_code) DO NOTHING;

INSERT INTO kb.product_node(parent_product_node_id, product_code, product_name, product_level, release_family, display_order)
SELECT p.product_node_id, x.code, x.name, 'PRODUCT_FAMILY', 'FUSION_APPLICATIONS', x.ord
FROM kb.product_node p
CROSS JOIN (VALUES
    ('APPLICATIONS_COMMON','Applications Common',10),
    ('ERP','Enterprise Resource Planning',20),
    ('SCM','Supply Chain and Manufacturing',30),
    ('HCM','Human Capital Management',40),
    ('CX','Customer Experience',50),
    ('FUSION_AI','Oracle AI for Fusion Applications',60)
) AS x(code,name,ord)
WHERE p.product_code = 'FUSION_APPLICATIONS'
ON CONFLICT (tenant_id, product_code) DO NOTHING;

INSERT INTO kb.product_node(parent_product_node_id, product_code, product_name, product_level, release_family, display_order)
SELECT p.product_node_id, x.code, x.name, 'PRODUCT', 'FUSION_APPLICATIONS', x.ord
FROM kb.product_node p
JOIN (VALUES
    ('ERP','FINANCIALS','Financials',10),
    ('ERP','PROCUREMENT','Procurement',20),
    ('ERP','PROJECT_MANAGEMENT','Project Management',30),
    ('ERP','RISK_MANAGEMENT','Risk Management and Compliance',40),
    ('ERP','ENTERPRISE_DATA_MANAGEMENT','Enterprise Data Management',50),
    ('SCM','PRODUCT_MANAGEMENT','Product Management',10),
    ('SCM','SUPPLY_CHAIN_PLANNING','Supply Chain Planning',20),
    ('SCM','MANUFACTURING','Manufacturing',30),
    ('SCM','INVENTORY_MANAGEMENT','Inventory Management',40),
    ('SCM','ORDER_MANAGEMENT','Order Management',50),
    ('SCM','LOGISTICS','Logistics',60),
    ('SCM','MAINTENANCE','Maintenance',70),
    ('HCM','GLOBAL_HR','Global Human Resources',10),
    ('HCM','PAYROLL','Payroll',20),
    ('HCM','TIME_AND_LABOR','Time and Labor',30),
    ('HCM','ABSENCE_MANAGEMENT','Absence Management',40),
    ('HCM','BENEFITS','Benefits',50),
    ('HCM','RECRUITING','Recruiting',60),
    ('HCM','TALENT_MANAGEMENT','Talent Management',70),
    ('CX','SALES','Sales',10),
    ('CX','FUSION_SERVICE','Fusion Service',20),
    ('CX','SUBSCRIPTION_MANAGEMENT','Subscription Management',30),
    ('APPLICATIONS_COMMON','OTBI','Oracle Transactional Business Intelligence',10),
    ('APPLICATIONS_COMMON','BI_PUBLISHER','BI Publisher',20),
    ('APPLICATIONS_COMMON','SECURITY','Security',30),
    ('APPLICATIONS_COMMON','REST_API','REST APIs',40),
    ('FUSION_AI','AI_AGENT_STUDIO','AI Agent Studio',10)
) AS x(parent_code,code,name,ord)
  ON p.product_code = x.parent_code
ON CONFLICT (tenant_id, product_code) DO NOTHING;

COMMIT;
