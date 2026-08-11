"""Tenant-scoped administration reads and access mutations over identity data."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

_OVERVIEW = text("""
SELECT
  (SELECT count(*) FROM identity.app_user app_user
    WHERE app_user.tenant_id=:tenant_id AND app_user.active_flag) AS active_users,
  (SELECT count(*) FROM identity.support_group support_group
    WHERE support_group.tenant_id=:tenant_id AND support_group.active_flag) AS support_groups,
  (SELECT count(*) FROM itsm.ticket ticket
    JOIN config.workflow_status status ON status.status_id=ticket.status_id
    WHERE ticket.tenant_id=:tenant_id AND NOT status.terminal_flag) AS open_tickets,
  (SELECT count(*) FROM kb.document document
    JOIN kb.document_version version ON version.document_id=document.document_id
      AND version.current_version_flag
      AND version.published_processing_version_id IS NOT NULL
    WHERE (document.tenant_id IS NULL OR document.tenant_id=:tenant_id)
      AND document.active_flag
      AND document.approval_status='APPROVED') AS published_knowledge_documents
""")

_AUDIT_EVENTS = text("""
SELECT audit_event_id,actor_id,actor_type,action_code,resource_type,resource_id,
  outcome_code,failure_reason,change_summary_json,correlation_id,request_id,occurred_at
FROM audit.audit_event
WHERE tenant_id=:tenant_id
  AND (CAST(:resource_type AS text) IS NULL OR resource_type=:resource_type)
  AND (CAST(:action_code AS text) IS NULL OR action_code=:action_code)
  AND (CAST(:outcome_code AS text) IS NULL OR outcome_code=:outcome_code)
  AND (CAST(:occurred_from AS timestamptz) IS NULL OR occurred_at>=:occurred_from)
  AND (CAST(:occurred_to AS timestamptz) IS NULL OR occurred_at<=:occurred_to)
ORDER BY occurred_at DESC,audit_event_id DESC
LIMIT :result_limit OFFSET :result_offset
""")

_USERS = text("""
SELECT app_user.user_id,app_user.display_name,app_user.email_address,app_user.active_flag,
  app_user.created_at,app_user.updated_at,business_unit.business_unit_name,
  COALESCE((SELECT array_agg(effective_role.role_code ORDER BY effective_role.role_code)
    FROM (SELECT DISTINCT user_role.role_code FROM identity.user_role user_role
      WHERE user_role.tenant_id=:tenant_id AND user_role.user_id=app_user.user_id
        AND user_role.active_flag AND user_role.valid_from<=CURRENT_TIMESTAMP
        AND (user_role.valid_to IS NULL OR user_role.valid_to>CURRENT_TIMESTAMP)
    ) effective_role),CAST('{}' AS text[])) AS role_codes,
  COALESCE((SELECT array_agg(support_group.group_name ORDER BY support_group.group_name)
    FROM identity.support_group_member member
    JOIN identity.support_group support_group
      ON support_group.support_group_id=member.support_group_id
      AND support_group.tenant_id=:tenant_id AND support_group.active_flag
    WHERE member.user_id=app_user.user_id AND member.active_flag),
    CAST('{}' AS text[])) AS support_group_names,
  COALESCE((SELECT array_agg(provider.provider_code ORDER BY provider.provider_code)
    FROM (SELECT DISTINCT mapping.provider_code FROM identity.external_identity external_identity
      JOIN identity.oidc_tenant_mapping mapping
        ON mapping.oidc_tenant_mapping_id=external_identity.oidc_tenant_mapping_id
      WHERE external_identity.tenant_id=:tenant_id
        AND external_identity.user_id=app_user.user_id AND external_identity.active_flag
    ) provider),CAST('{}' AS text[])) AS identity_provider_codes
FROM identity.app_user app_user
LEFT JOIN identity.business_unit business_unit
  ON business_unit.business_unit_id=app_user.business_unit_id
WHERE app_user.tenant_id=:tenant_id
  AND (CAST(:active AS boolean) IS NULL OR app_user.active_flag=:active)
  AND (CAST(:search_pattern AS text) IS NULL
    OR app_user.display_name ILIKE :search_pattern ESCAPE '\\'
    OR app_user.email_address ILIKE :search_pattern ESCAPE '\\')
  AND (CAST(:role_code AS text) IS NULL OR EXISTS (
    SELECT 1 FROM identity.user_role filter_role
    WHERE filter_role.tenant_id=:tenant_id AND filter_role.user_id=app_user.user_id
      AND filter_role.role_code=:role_code AND filter_role.active_flag
      AND filter_role.valid_from<=CURRENT_TIMESTAMP
      AND (filter_role.valid_to IS NULL OR filter_role.valid_to>CURRENT_TIMESTAMP)))
  AND (CAST(:support_group_id AS uuid) IS NULL OR EXISTS (
    SELECT 1 FROM identity.support_group_member filter_member
    JOIN identity.support_group filter_group
      ON filter_group.support_group_id=filter_member.support_group_id
      AND filter_group.tenant_id=:tenant_id
    WHERE filter_member.user_id=app_user.user_id AND filter_member.active_flag
      AND filter_member.support_group_id=:support_group_id))
  AND (CAST(:provider_code AS text) IS NULL OR EXISTS (
    SELECT 1 FROM identity.external_identity filter_identity
    JOIN identity.oidc_tenant_mapping filter_mapping
      ON filter_mapping.oidc_tenant_mapping_id=filter_identity.oidc_tenant_mapping_id
    WHERE filter_identity.tenant_id=:tenant_id AND filter_identity.user_id=app_user.user_id
      AND filter_identity.active_flag AND filter_mapping.provider_code=:provider_code))
ORDER BY app_user.display_name,app_user.user_id
LIMIT :result_limit OFFSET :result_offset
""")

_USER_PROFILE = text("""
SELECT app_user.user_id,app_user.display_name,app_user.email_address,app_user.active_flag,
  app_user.external_subject,app_user.locale_code,app_user.timezone_name,
  app_user.created_at,app_user.updated_at,business_unit.business_unit_name,
  COALESCE((SELECT json_agg(json_build_object(
      'provider_code',mapping.provider_code,
      'active_flag',external_identity.active_flag,
      'last_authenticated_at',external_identity.last_authenticated_at)
      ORDER BY mapping.provider_code)
    FROM identity.external_identity external_identity
    JOIN identity.oidc_tenant_mapping mapping
      ON mapping.oidc_tenant_mapping_id=external_identity.oidc_tenant_mapping_id
    WHERE external_identity.tenant_id=:tenant_id
      AND external_identity.user_id=app_user.user_id),CAST('[]' AS json)) AS external_identities
FROM identity.app_user app_user
LEFT JOIN identity.business_unit business_unit
  ON business_unit.business_unit_id=app_user.business_unit_id
WHERE app_user.tenant_id=:tenant_id AND app_user.user_id=:user_id
""")

_USER_ROLES = text("""
SELECT user_role.role_code,role_definition.role_name,user_role.active_flag,
  user_role.valid_from,user_role.valid_to
FROM identity.user_role user_role
JOIN identity.role_definition role_definition
  ON role_definition.role_code=user_role.role_code AND role_definition.active_flag
WHERE user_role.tenant_id=:tenant_id AND user_role.user_id=:user_id
  AND user_role.active_flag AND user_role.valid_from<=CURRENT_TIMESTAMP
  AND (user_role.valid_to IS NULL OR user_role.valid_to>CURRENT_TIMESTAMP)
ORDER BY user_role.role_code,user_role.valid_from DESC
""")

_USER_MEMBERSHIPS = text("""
SELECT member.support_group_id,support_group.group_name,member.member_role,
  member.active_flag,member.joined_at
FROM identity.support_group_member member
JOIN identity.support_group support_group
  ON support_group.support_group_id=member.support_group_id
  AND support_group.tenant_id=:tenant_id
WHERE member.user_id=:user_id
ORDER BY support_group.group_name,member.support_group_id
""")

_USER_SECURITY_EVENTS = text("""
SELECT security_event_id,event_type,decision_code,user_id,resource_type,resource_id,
  event_data_json,occurred_at
FROM audit.security_event
WHERE tenant_id=:tenant_id AND user_id=:user_id
ORDER BY occurred_at DESC,security_event_id DESC
LIMIT :result_limit
""")

_ROLES = text("""
SELECT role_definition.role_code,role_definition.role_name,role_definition.description,
  role_definition.system_role_flag,role_definition.active_flag,
  COALESCE(assignment.assigned_user_count,0) AS assigned_user_count
FROM identity.role_definition role_definition
LEFT JOIN (
  SELECT user_role.role_code,count(DISTINCT user_role.user_id) AS assigned_user_count
  FROM identity.user_role user_role
  WHERE user_role.tenant_id=:tenant_id AND user_role.active_flag
    AND user_role.valid_from<=CURRENT_TIMESTAMP
    AND (user_role.valid_to IS NULL OR user_role.valid_to>CURRENT_TIMESTAMP)
  GROUP BY user_role.role_code) assignment
  ON assignment.role_code=role_definition.role_code
WHERE (CAST(:search_pattern AS text) IS NULL
  OR role_definition.role_code ILIKE :search_pattern ESCAPE '\\'
  OR role_definition.role_name ILIKE :search_pattern ESCAPE '\\')
ORDER BY role_definition.role_code
LIMIT :result_limit OFFSET :result_offset
""")

_ROLE = text("""
SELECT role_code,role_name,description,system_role_flag,active_flag
FROM identity.role_definition
WHERE role_code=:role_code
""")

_ROLE_ASSIGNMENTS = text("""
SELECT app_user.user_id,app_user.display_name,app_user.email_address,app_user.active_flag,
  user_role.valid_from,user_role.valid_to
FROM identity.user_role user_role
JOIN identity.app_user app_user
  ON app_user.user_id=user_role.user_id AND app_user.tenant_id=:tenant_id
WHERE user_role.tenant_id=:tenant_id AND user_role.role_code=:role_code
  AND user_role.active_flag AND user_role.valid_from<=CURRENT_TIMESTAMP
  AND (user_role.valid_to IS NULL OR user_role.valid_to>CURRENT_TIMESTAMP)
ORDER BY app_user.display_name,app_user.user_id
LIMIT :result_limit OFFSET :result_offset
""")

_QUEUES = text("""
SELECT support_group.support_group_id,support_group.group_code,support_group.group_name,
  support_group.email_address,support_group.assignment_method,support_group.active_flag,
  support_group.created_at,support_group.updated_at,
  COALESCE(member.member_count,0) AS member_count
FROM identity.support_group support_group
LEFT JOIN (
  SELECT support_group_member.support_group_id,count(*) AS member_count
  FROM identity.support_group_member support_group_member
  WHERE support_group_member.active_flag
  GROUP BY support_group_member.support_group_id) member
  ON member.support_group_id=support_group.support_group_id
WHERE support_group.tenant_id=:tenant_id
  AND (CAST(:active AS boolean) IS NULL OR support_group.active_flag=:active)
  AND (CAST(:search_pattern AS text) IS NULL
    OR support_group.group_code ILIKE :search_pattern ESCAPE '\\'
    OR support_group.group_name ILIKE :search_pattern ESCAPE '\\')
ORDER BY support_group.group_name,support_group.support_group_id
LIMIT :result_limit OFFSET :result_offset
""")

_QUEUE = text("""
SELECT support_group.support_group_id,support_group.group_code,support_group.group_name,
  support_group.email_address,support_group.assignment_method,support_group.active_flag,
  support_group.created_at,support_group.updated_at,
  manager.display_name AS manager_display_name
FROM identity.support_group support_group
LEFT JOIN identity.app_user manager ON manager.user_id=support_group.manager_user_id
WHERE support_group.tenant_id=:tenant_id AND support_group.support_group_id=:support_group_id
""")

_QUEUE_MEMBERS = text("""
SELECT member.user_id,app_user.display_name,member.member_role,member.active_flag,
  member.joined_at
FROM identity.support_group_member member
JOIN identity.support_group support_group
  ON support_group.support_group_id=member.support_group_id
  AND support_group.tenant_id=:tenant_id
JOIN identity.app_user app_user ON app_user.user_id=member.user_id
WHERE member.support_group_id=:support_group_id
ORDER BY app_user.display_name,member.user_id
""")

_TICKET_VIEWS = text("""
SELECT queue_definition.queue_id,queue_definition.queue_name,queue_definition.description,
  service_project.project_key AS project_code,queue_definition.visibility_type,
  queue_definition.display_order,queue_definition.active_flag,version.version_status
FROM config.queue_definition queue_definition
JOIN config.service_project service_project
  ON service_project.project_id=queue_definition.project_id
LEFT JOIN LATERAL (
  SELECT queue_definition_version.version_status
  FROM config.queue_definition_version queue_definition_version
  WHERE queue_definition_version.queue_id=queue_definition.queue_id
  ORDER BY queue_definition_version.version_number DESC
  LIMIT 1) version ON true
WHERE queue_definition.tenant_id=:tenant_id
  AND (CAST(:owner_group_id AS uuid) IS NULL
    OR queue_definition.owner_group_id=:owner_group_id)
ORDER BY queue_definition.display_order,queue_definition.queue_name,queue_definition.queue_id
LIMIT :result_limit OFFSET :result_offset
""")

_LOCK_TENANT_IDENTITY = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:tenant_id AS text), 0))"
)

_USER_FOR_UPDATE = text("""
SELECT user_id,display_name,active_flag,updated_at
FROM identity.app_user
WHERE tenant_id=:tenant_id AND user_id=:user_id
FOR UPDATE
""")

_ACTIVE_ADMIN_COUNT = text("""
SELECT count(DISTINCT user_role.user_id) AS admin_count
FROM identity.user_role
JOIN identity.app_user
  ON app_user.user_id=user_role.user_id
  AND app_user.tenant_id=:tenant_id AND app_user.active_flag
WHERE user_role.tenant_id=:tenant_id AND user_role.role_code=:role_code
  AND user_role.active_flag AND user_role.valid_from<=CURRENT_TIMESTAMP
  AND (user_role.valid_to IS NULL OR user_role.valid_to>CURRENT_TIMESTAMP)
  AND user_role.user_id<>:excluded_user_id
""")

_SET_USER_ACTIVE = text("""
UPDATE identity.app_user SET active_flag=:active
WHERE tenant_id=:tenant_id AND user_id=:user_id
RETURNING updated_at
""")

_ACTIVE_ROLE_DEFINITION = text("""
SELECT role_code FROM identity.role_definition
WHERE role_code=:role_code AND active_flag
""")

_ACTIVE_ASSIGNMENT = text("""
SELECT valid_from FROM identity.user_role
WHERE tenant_id=:tenant_id AND user_id=:user_id AND role_code=:role_code
  AND active_flag AND valid_from<=CURRENT_TIMESTAMP
  AND (valid_to IS NULL OR valid_to>CURRENT_TIMESTAMP)
ORDER BY valid_from DESC
LIMIT 1
""")

_INSERT_ASSIGNMENT = text("""
INSERT INTO identity.user_role(tenant_id,user_id,role_code,granted_by)
VALUES (:tenant_id,:user_id,:role_code,:granted_by)
RETURNING valid_from
""")

_CLOSE_ASSIGNMENTS = text("""
UPDATE identity.user_role
SET active_flag=false,valid_to=CURRENT_TIMESTAMP
WHERE tenant_id=:tenant_id AND user_id=:user_id AND role_code=:role_code
  AND active_flag AND valid_from<=CURRENT_TIMESTAMP
  AND (valid_to IS NULL OR valid_to>CURRENT_TIMESTAMP)
""")

_QUEUE_FOR_TENANT = text("""
SELECT support_group_id,group_name FROM identity.support_group
WHERE tenant_id=:tenant_id AND support_group_id=:support_group_id
""")

_MEMBERSHIP_FOR_UPDATE = text("""
SELECT member_role,active_flag FROM identity.support_group_member
WHERE support_group_id=:support_group_id AND user_id=:user_id
FOR UPDATE
""")

_UPSERT_MEMBER = text("""
INSERT INTO identity.support_group_member(support_group_id,user_id,member_role)
VALUES (:support_group_id,:user_id,:member_role)
ON CONFLICT (support_group_id,user_id)
DO UPDATE SET active_flag=true,member_role=EXCLUDED.member_role
""")

_DEACTIVATE_MEMBER = text("""
UPDATE identity.support_group_member SET active_flag=false
WHERE support_group_id=:support_group_id AND user_id=:user_id AND active_flag
""")

_INSERT_ADMIN_AUDIT_EVENT = text("""
INSERT INTO audit.audit_event(
  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
  change_summary_json,outcome_code)
VALUES (:tenant_id,:actor_id,'USER',:action_code,:resource_type,:resource_id,
  CAST(:change_summary AS jsonb),'SUCCESS')
""")

# The "displayed" configuration version is the currently effective published
# version when one exists, otherwise the newest version of any status. The
# boolean sort key makes the published pick win without a second query.
_CURRENT_VERSION_PICK = """
  ORDER BY (candidate.version_status='PUBLISHED' AND candidate.published_at IS NOT NULL
      AND candidate.published_at<=CURRENT_TIMESTAMP
      AND (candidate.effective_from IS NULL OR candidate.effective_from<=CURRENT_TIMESTAMP)
      AND (candidate.effective_to IS NULL OR candidate.effective_to>CURRENT_TIMESTAMP)) DESC,
    candidate.version_number DESC
  LIMIT 1
"""

_WORKFLOWS = text(f"""
SELECT workflow.workflow_id,workflow.workflow_code,workflow.workflow_name,workflow.description,
  workflow.active_flag,workflow.created_at,
  current_version.version_number AS current_version_number,
  current_version.version_status AS current_version_status,
  COALESCE((SELECT count(*) FROM config.workflow_status status
    WHERE status.workflow_version_id=current_version.workflow_version_id),0) AS status_count,
  COALESCE((SELECT count(*) FROM config.workflow_transition transition
    WHERE transition.workflow_version_id=current_version.workflow_version_id),0)
    AS transition_count,
  (SELECT count(*) FROM config.request_type request_type
    WHERE request_type.tenant_id=:tenant_id
      AND request_type.workflow_id=workflow.workflow_id) AS request_type_count,
  (SELECT count(*) FROM itsm.ticket ticket
    JOIN config.workflow_version ticket_version
      ON ticket_version.workflow_version_id=ticket.workflow_version_id
    WHERE ticket.tenant_id=:tenant_id
      AND ticket_version.workflow_id=workflow.workflow_id) AS ticket_count
FROM config.workflow workflow
LEFT JOIN LATERAL (
  SELECT candidate.workflow_version_id,candidate.version_number,candidate.version_status
  FROM config.workflow_version candidate
  WHERE candidate.workflow_id=workflow.workflow_id
{_CURRENT_VERSION_PICK}) current_version ON true
WHERE workflow.tenant_id=:tenant_id
  AND (CAST(:active AS boolean) IS NULL OR workflow.active_flag=:active)
  AND (CAST(:search_pattern AS text) IS NULL
    OR workflow.workflow_code ILIKE :search_pattern ESCAPE '\\'
    OR workflow.workflow_name ILIKE :search_pattern ESCAPE '\\')
ORDER BY workflow.workflow_name,workflow.workflow_id
LIMIT :result_limit OFFSET :result_offset
""")

_WORKFLOW = text(f"""
SELECT workflow.workflow_id,workflow.workflow_code,workflow.workflow_name,workflow.description,
  workflow.active_flag,workflow.created_at,
  current_version.workflow_version_id AS displayed_version_id,
  current_version.version_number AS displayed_version_number,
  current_version.version_status AS displayed_version_status,
  COALESCE((SELECT json_agg(json_build_object(
      'workflow_version_id',version.workflow_version_id,
      'version_number',version.version_number,
      'version_status',version.version_status,
      'effective_from',version.effective_from,
      'effective_to',version.effective_to,
      'published_at',version.published_at,
      'published_by_display_name',publisher.display_name,
      'created_at',version.created_at,
      'ticket_count',(SELECT count(*) FROM itsm.ticket ticket
        WHERE ticket.tenant_id=:tenant_id
          AND ticket.workflow_version_id=version.workflow_version_id))
      ORDER BY version.version_number DESC)
    FROM config.workflow_version version
    LEFT JOIN identity.app_user publisher ON publisher.user_id=version.published_by
    WHERE version.workflow_id=workflow.workflow_id),CAST('[]' AS json)) AS versions,
  COALESCE((SELECT json_agg(json_build_object(
      'request_type_id',request_type.request_type_id,
      'request_type_code',request_type.request_type_code,
      'request_type_name',request_type.request_type_name,
      'active_flag',request_type.active_flag,
      'employee_visible_flag',request_type.employee_visible_flag)
      ORDER BY request_type.request_type_name,request_type.request_type_id)
    FROM config.request_type request_type
    WHERE request_type.tenant_id=:tenant_id
      AND request_type.workflow_id=workflow.workflow_id),CAST('[]' AS json)) AS request_types
FROM config.workflow workflow
LEFT JOIN LATERAL (
  SELECT candidate.workflow_version_id,candidate.version_number,candidate.version_status
  FROM config.workflow_version candidate
  WHERE candidate.workflow_id=workflow.workflow_id
{_CURRENT_VERSION_PICK}) current_version ON true
WHERE workflow.tenant_id=:tenant_id AND workflow.workflow_id=:workflow_id
""")

_WORKFLOW_STATUSES = text("""
SELECT status_id,status_code,status_name,status_category,initial_flag,terminal_flag,
  customer_visible_name,display_order
FROM config.workflow_status
WHERE workflow_version_id=:workflow_version_id
ORDER BY display_order,status_code
""")

_WORKFLOW_TRANSITIONS = text("""
SELECT transition.transition_id,transition.transition_code,transition.transition_name,
  from_status.status_code AS from_status_code,from_status.status_name AS from_status_name,
  to_status.status_code AS to_status_code,to_status.status_name AS to_status_name,
  transition.display_order,transition.active_flag,
  transition.condition_json,transition.validator_json,transition.action_json
FROM config.workflow_transition transition
JOIN config.workflow_status from_status ON from_status.status_id=transition.from_status_id
JOIN config.workflow_status to_status ON to_status.status_id=transition.to_status_id
WHERE transition.workflow_version_id=:workflow_version_id
ORDER BY transition.display_order,transition.transition_code
""")

_SLA_POLICIES = text("""
SELECT definition.sla_definition_id,definition.sla_code,definition.sla_name,
  definition.metric_code,definition.active_flag,
  service_project.project_key,service_project.project_name,
  (SELECT count(*) FROM config.sla_goal goal
    WHERE goal.sla_definition_id=definition.sla_definition_id) AS goal_count,
  (SELECT count(*) FROM itsm.ticket_sla ticket_sla
    WHERE ticket_sla.tenant_id=:tenant_id
      AND ticket_sla.sla_definition_id=definition.sla_definition_id
      AND ticket_sla.state_code='RUNNING') AS running_cycle_count,
  (SELECT count(*) FROM itsm.ticket_sla ticket_sla
    WHERE ticket_sla.tenant_id=:tenant_id
      AND ticket_sla.sla_definition_id=definition.sla_definition_id
      AND ticket_sla.state_code='BREACHED') AS breached_cycle_count
FROM config.sla_definition definition
JOIN config.service_project service_project
  ON service_project.project_id=definition.project_id
WHERE definition.tenant_id=:tenant_id
  AND (CAST(:active AS boolean) IS NULL OR definition.active_flag=:active)
  AND (CAST(:project_id AS uuid) IS NULL OR definition.project_id=:project_id)
  AND (CAST(:search_pattern AS text) IS NULL
    OR definition.sla_code ILIKE :search_pattern ESCAPE '\\'
    OR definition.sla_name ILIKE :search_pattern ESCAPE '\\')
ORDER BY definition.sla_name,definition.sla_definition_id
LIMIT :result_limit OFFSET :result_offset
""")

_SLA_POLICY = text("""
SELECT definition.sla_definition_id,definition.sla_code,definition.sla_name,
  definition.metric_code,definition.description,definition.active_flag,
  definition.start_condition_json,definition.pause_condition_json,definition.stop_condition_json,
  service_project.project_key,service_project.project_name,
  COALESCE((SELECT json_agg(json_build_object(
      'sla_definition_version_id',version.sla_definition_version_id,
      'version_number',version.version_number,
      'version_status',version.version_status,
      'effective_from',version.effective_from,
      'effective_to',version.effective_to,
      'published_at',version.published_at)
      ORDER BY version.version_number DESC)
    FROM config.sla_definition_version version
    WHERE version.sla_definition_id=definition.sla_definition_id),
    CAST('[]' AS json)) AS versions,
  (SELECT count(*) FROM itsm.ticket_sla cycle WHERE cycle.tenant_id=:tenant_id
    AND cycle.sla_definition_id=definition.sla_definition_id
    AND cycle.state_code='PENDING') AS pending_count,
  (SELECT count(*) FROM itsm.ticket_sla cycle WHERE cycle.tenant_id=:tenant_id
    AND cycle.sla_definition_id=definition.sla_definition_id
    AND cycle.state_code='RUNNING') AS running_count,
  (SELECT count(*) FROM itsm.ticket_sla cycle WHERE cycle.tenant_id=:tenant_id
    AND cycle.sla_definition_id=definition.sla_definition_id
    AND cycle.state_code='PAUSED') AS paused_count,
  (SELECT count(*) FROM itsm.ticket_sla cycle WHERE cycle.tenant_id=:tenant_id
    AND cycle.sla_definition_id=definition.sla_definition_id
    AND cycle.state_code='COMPLETED') AS completed_count,
  (SELECT count(*) FROM itsm.ticket_sla cycle WHERE cycle.tenant_id=:tenant_id
    AND cycle.sla_definition_id=definition.sla_definition_id
    AND cycle.state_code='BREACHED') AS breached_count,
  (SELECT count(*) FROM itsm.ticket_sla cycle WHERE cycle.tenant_id=:tenant_id
    AND cycle.sla_definition_id=definition.sla_definition_id
    AND cycle.state_code='CANCELLED') AS cancelled_count
FROM config.sla_definition definition
JOIN config.service_project service_project
  ON service_project.project_id=definition.project_id
WHERE definition.tenant_id=:tenant_id AND definition.sla_definition_id=:sla_definition_id
""")

_SLA_GOALS = text(f"""
SELECT goal.sla_goal_id,goal.goal_name,goal.priority_order,goal.active_flag,
  goal_version.version_number,goal_version.version_status,
  goal_version.target_minutes,goal_version.warning_minutes,goal_version.match_condition_json,
  calendar.calendar_code,calendar.calendar_name
FROM config.sla_goal goal
LEFT JOIN LATERAL (
  SELECT candidate.sla_goal_version_id,candidate.version_number,candidate.version_status,
    candidate.target_minutes,candidate.warning_minutes,candidate.match_condition_json,
    candidate.business_calendar_version_id
  FROM config.sla_goal_version candidate
  WHERE candidate.sla_goal_id=goal.sla_goal_id
{_CURRENT_VERSION_PICK}) goal_version ON true
LEFT JOIN config.business_calendar_version calendar_version
  ON calendar_version.business_calendar_version_id=goal_version.business_calendar_version_id
LEFT JOIN config.business_calendar calendar
  ON calendar.calendar_id=calendar_version.calendar_id
WHERE goal.sla_definition_id=:sla_definition_id
ORDER BY goal.priority_order,goal.goal_name,goal.sla_goal_id
""")

_CALENDARS = text(f"""
SELECT calendar.calendar_id,calendar.calendar_code,calendar.calendar_name,
  calendar.timezone_name,calendar.twenty_four_seven_flag,calendar.active_flag,
  current_version.version_number AS current_version_number,
  current_version.version_status AS current_version_status,
  (SELECT count(DISTINCT goal_version.sla_goal_id)
    FROM config.sla_goal_version goal_version
    JOIN config.business_calendar_version link_version
      ON link_version.business_calendar_version_id=goal_version.business_calendar_version_id
    JOIN config.sla_goal goal ON goal.sla_goal_id=goal_version.sla_goal_id
    JOIN config.sla_definition definition
      ON definition.sla_definition_id=goal.sla_definition_id
      AND definition.tenant_id=:tenant_id
    WHERE link_version.calendar_id=calendar.calendar_id) AS linked_goal_count
FROM config.business_calendar calendar
LEFT JOIN LATERAL (
  SELECT candidate.business_calendar_version_id,candidate.version_number,candidate.version_status
  FROM config.business_calendar_version candidate
  WHERE candidate.calendar_id=calendar.calendar_id
{_CURRENT_VERSION_PICK}) current_version ON true
WHERE calendar.tenant_id=:tenant_id
  AND (CAST(:active AS boolean) IS NULL OR calendar.active_flag=:active)
  AND (CAST(:search_pattern AS text) IS NULL
    OR calendar.calendar_code ILIKE :search_pattern ESCAPE '\\'
    OR calendar.calendar_name ILIKE :search_pattern ESCAPE '\\')
ORDER BY calendar.calendar_name,calendar.calendar_id
LIMIT :result_limit OFFSET :result_offset
""")

_CALENDAR = text(f"""
SELECT calendar.calendar_id,calendar.calendar_code,calendar.calendar_name,
  calendar.timezone_name,calendar.twenty_four_seven_flag,calendar.active_flag,
  current_version.business_calendar_version_id AS displayed_version_id,
  current_version.version_number AS displayed_version_number,
  current_version.version_status AS displayed_version_status,
  COALESCE((SELECT json_agg(json_build_object(
      'business_calendar_version_id',version.business_calendar_version_id,
      'version_number',version.version_number,
      'version_status',version.version_status,
      'timezone_name',version.timezone_name,
      'twenty_four_seven_flag',version.twenty_four_seven_flag,
      'effective_from',version.effective_from,
      'effective_to',version.effective_to,
      'published_at',version.published_at)
      ORDER BY version.version_number DESC)
    FROM config.business_calendar_version version
    WHERE version.calendar_id=calendar.calendar_id),CAST('[]' AS json)) AS versions,
  COALESCE((SELECT json_agg(json_build_object(
      'sla_code',linked.sla_code,'goal_name',linked.goal_name)
      ORDER BY linked.sla_code,linked.goal_name)
    FROM (SELECT DISTINCT definition.sla_code,goal.goal_name
      FROM config.sla_goal_version goal_version
      JOIN config.business_calendar_version link_version
        ON link_version.business_calendar_version_id=goal_version.business_calendar_version_id
      JOIN config.sla_goal goal ON goal.sla_goal_id=goal_version.sla_goal_id
      JOIN config.sla_definition definition
        ON definition.sla_definition_id=goal.sla_definition_id
        AND definition.tenant_id=:tenant_id
      WHERE link_version.calendar_id=calendar.calendar_id) linked),
    CAST('[]' AS json)) AS linked_goals
FROM config.business_calendar calendar
LEFT JOIN LATERAL (
  SELECT candidate.business_calendar_version_id,candidate.version_number,candidate.version_status
  FROM config.business_calendar_version candidate
  WHERE candidate.calendar_id=calendar.calendar_id
{_CURRENT_VERSION_PICK}) current_version ON true
WHERE calendar.tenant_id=:tenant_id AND calendar.calendar_id=:calendar_id
""")

_CALENDAR_WORKING_PERIODS = text("""
SELECT iso_day_of_week,start_local_time,end_local_time
FROM config.calendar_working_period
WHERE business_calendar_version_id=:business_calendar_version_id
ORDER BY iso_day_of_week,start_local_time
""")

_CALENDAR_EXCEPTIONS = text("""
SELECT exception_date,exception_type,start_local_time,end_local_time,description
FROM config.calendar_exception
WHERE business_calendar_version_id=:business_calendar_version_id
ORDER BY exception_date
""")

_REQUEST_TYPES = text(f"""
SELECT request_type.request_type_id,request_type.request_type_code,
  request_type.request_type_name,request_type.portal_group,
  request_type.employee_visible_flag,request_type.active_flag,request_type.display_order,
  request_type.updated_at,
  service_project.project_key,service_project.project_name,
  work_type.work_type_code,workflow.workflow_code,workflow.workflow_name,
  current_version.version_number AS current_version_number,
  current_version.version_status AS current_version_status
FROM config.request_type request_type
JOIN config.service_project service_project
  ON service_project.project_id=request_type.project_id
JOIN config.work_type work_type ON work_type.work_type_id=request_type.work_type_id
JOIN config.workflow workflow ON workflow.workflow_id=request_type.workflow_id
LEFT JOIN LATERAL (
  SELECT candidate.request_type_version_id,candidate.version_number,candidate.version_status
  FROM config.request_type_version candidate
  WHERE candidate.request_type_id=request_type.request_type_id
{_CURRENT_VERSION_PICK}) current_version ON true
WHERE request_type.tenant_id=:tenant_id
  AND (CAST(:active AS boolean) IS NULL OR request_type.active_flag=:active)
  AND (CAST(:project_id AS uuid) IS NULL OR request_type.project_id=:project_id)
  AND (CAST(:search_pattern AS text) IS NULL
    OR request_type.request_type_code ILIKE :search_pattern ESCAPE '\\'
    OR request_type.request_type_name ILIKE :search_pattern ESCAPE '\\')
ORDER BY COALESCE(request_type.portal_group,''),request_type.display_order,
  request_type.request_type_name,request_type.request_type_id
LIMIT :result_limit OFFSET :result_offset
""")

_REQUEST_TYPE = text(f"""
SELECT request_type.request_type_id,request_type.request_type_code,
  request_type.request_type_name,request_type.portal_description,request_type.portal_group,
  request_type.icon_name,request_type.employee_visible_flag,request_type.active_flag,
  request_type.display_order,request_type.created_at,request_type.updated_at,
  service_project.project_key,service_project.project_name,work_type.work_type_code,
  workflow.workflow_id,workflow.workflow_code,workflow.workflow_name,
  current_version.request_type_version_id AS displayed_version_id,
  current_version.version_number AS displayed_version_number,
  current_version.version_status AS displayed_version_status,
  COALESCE((SELECT json_agg(json_build_object(
      'request_type_version_id',version.request_type_version_id,
      'version_number',version.version_number,
      'version_status',version.version_status,
      'effective_from',version.effective_from,
      'effective_to',version.effective_to,
      'published_at',version.published_at)
      ORDER BY version.version_number DESC)
    FROM config.request_type_version version
    WHERE version.request_type_id=request_type.request_type_id),
    CAST('[]' AS json)) AS versions
FROM config.request_type request_type
JOIN config.service_project service_project
  ON service_project.project_id=request_type.project_id
JOIN config.work_type work_type ON work_type.work_type_id=request_type.work_type_id
JOIN config.workflow workflow ON workflow.workflow_id=request_type.workflow_id
LEFT JOIN LATERAL (
  SELECT candidate.request_type_version_id,candidate.version_number,candidate.version_status
  FROM config.request_type_version candidate
  WHERE candidate.request_type_id=request_type.request_type_id
{_CURRENT_VERSION_PICK}) current_version ON true
WHERE request_type.tenant_id=:tenant_id AND request_type.request_type_id=:request_type_id
""")

_REQUEST_TYPE_FORM_FIELDS = text("""
SELECT custom_field.field_code,
  COALESCE(form_field.display_label,custom_field.field_name) AS label,
  custom_field.data_type,form_field.required_flag,form_field.hidden_flag,
  form_field.display_order,form_field.help_text,form_field.condition_json,
  COALESCE((SELECT json_agg(json_build_object(
      'option_code',field_option.option_code,
      'option_label',field_option.option_label,
      'display_order',field_option.display_order,
      'active_flag',field_option.active_flag)
      ORDER BY field_option.display_order,field_option.option_code)
    FROM config.custom_field_option field_option
    WHERE field_option.custom_field_id=custom_field.custom_field_id),
    CAST('[]' AS json)) AS options
FROM config.request_type_field form_field
JOIN config.custom_field custom_field
  ON custom_field.custom_field_id=form_field.custom_field_id
  AND custom_field.tenant_id=:tenant_id
WHERE form_field.request_type_version_id=:request_type_version_id
ORDER BY form_field.display_order,custom_field.field_code
""")

_REQUEST_TYPE_FOR_UPDATE = text("""
SELECT request_type_id,request_type_name,active_flag,employee_visible_flag,updated_at
FROM config.request_type
WHERE tenant_id=:tenant_id AND request_type_id=:request_type_id
FOR UPDATE
""")

_SET_REQUEST_TYPE_VISIBILITY = text("""
UPDATE config.request_type
SET active_flag=:active,employee_visible_flag=:employee_visible
WHERE tenant_id=:tenant_id AND request_type_id=:request_type_id
RETURNING active_flag,employee_visible_flag,updated_at
""")

_SECURITY_EVENTS = text("""
SELECT security_event_id,event_type,decision_code,user_id,resource_type,resource_id,
  event_data_json,occurred_at
FROM audit.security_event
WHERE tenant_id=:tenant_id
  AND (CAST(:event_type AS text) IS NULL OR event_type=:event_type)
  AND (CAST(:decision_code AS text) IS NULL OR decision_code=:decision_code)
  AND (CAST(:occurred_from AS timestamptz) IS NULL OR occurred_at>=:occurred_from)
  AND (CAST(:occurred_to AS timestamptz) IS NULL OR occurred_at<=:occurred_to)
ORDER BY occurred_at DESC,security_event_id DESC
LIMIT :result_limit OFFSET :result_offset
""")


@dataclass(frozen=True, slots=True)
class OverviewCounts:
    active_users: int
    support_groups: int
    open_tickets: int
    published_knowledge_documents: int


@dataclass(frozen=True, slots=True)
class AuditEventRow:
    id: int
    actor_id: str | None
    actor_type: str
    action_code: str
    resource_type: str
    resource_id: str | None
    outcome_code: str
    failure_reason: str | None
    change_summary: dict[str, Any]
    correlation_id: UUID | None
    request_id: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SecurityEventRow:
    id: int
    event_type: str
    decision_code: str
    user_id: UUID | None
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AdminUserRow:
    user_id: UUID
    display_name: str
    email_address: str
    active_flag: bool
    business_unit_name: str | None
    role_codes: tuple[str, ...]
    support_group_names: tuple[str, ...]
    identity_provider_codes: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ExternalIdentityRow:
    provider_code: str
    active_flag: bool
    last_authenticated_at: datetime | None


@dataclass(frozen=True, slots=True)
class AdminUserProfileRow:
    user_id: UUID
    display_name: str
    email_address: str
    active_flag: bool
    external_subject: str
    locale_code: str
    timezone_name: str
    business_unit_name: str | None
    external_identities: tuple[ExternalIdentityRow, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UserRoleRow:
    role_code: str
    role_name: str
    active_flag: bool
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True, slots=True)
class UserMembershipRow:
    support_group_id: UUID
    group_name: str
    member_role: str
    active_flag: bool
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class RoleSummaryRow:
    role_code: str
    role_name: str
    description: str | None
    system_role_flag: bool
    active_flag: bool
    assigned_user_count: int


@dataclass(frozen=True, slots=True)
class RoleAssignmentRow:
    user_id: UUID
    display_name: str
    email_address: str
    active_flag: bool
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True, slots=True)
class QueueSummaryRow:
    support_group_id: UUID
    group_code: str
    group_name: str
    contact_email: str | None
    assignment_method: str
    active_flag: bool
    member_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QueueDetailRow:
    support_group_id: UUID
    group_code: str
    group_name: str
    contact_email: str | None
    assignment_method: str
    active_flag: bool
    manager_display_name: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QueueMemberRow:
    user_id: UUID
    display_name: str
    member_role: str
    active_flag: bool
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class UserLockRow:
    user_id: UUID
    display_name: str
    active_flag: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QueueRefRow:
    support_group_id: UUID
    group_name: str


@dataclass(frozen=True, slots=True)
class MembershipStateRow:
    member_role: str
    active_flag: bool


@dataclass(frozen=True, slots=True)
class TicketViewRow:
    queue_id: UUID
    queue_name: str
    description: str | None
    project_code: str
    visibility: str
    display_order: int
    version_status: str | None
    active_flag: bool


@dataclass(frozen=True, slots=True)
class WorkflowSummaryRow:
    workflow_id: UUID
    workflow_code: str
    workflow_name: str
    description: str | None
    active_flag: bool
    current_version_number: int | None
    current_version_status: str | None
    status_count: int
    transition_count: int
    request_type_count: int
    ticket_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WorkflowVersionRow:
    workflow_version_id: UUID
    version_number: int
    version_status: str
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None
    published_by_display_name: str | None
    created_at: datetime
    ticket_count: int


@dataclass(frozen=True, slots=True)
class WorkflowRequestTypeRow:
    request_type_id: UUID
    request_type_code: str
    request_type_name: str
    active_flag: bool
    employee_visible_flag: bool


@dataclass(frozen=True, slots=True)
class WorkflowDetailRow:
    workflow_id: UUID
    workflow_code: str
    workflow_name: str
    description: str | None
    active_flag: bool
    created_at: datetime
    displayed_version_id: UUID | None
    displayed_version_number: int | None
    displayed_version_status: str | None
    versions: tuple[WorkflowVersionRow, ...]
    request_types: tuple[WorkflowRequestTypeRow, ...]


@dataclass(frozen=True, slots=True)
class WorkflowStatusRow:
    status_id: UUID
    status_code: str
    status_name: str
    status_category: str
    initial_flag: bool
    terminal_flag: bool
    customer_visible_name: str | None
    display_order: int


@dataclass(frozen=True, slots=True)
class WorkflowTransitionRow:
    transition_id: UUID
    transition_code: str
    transition_name: str
    from_status_code: str
    from_status_name: str
    to_status_code: str
    to_status_name: str
    display_order: int
    active_flag: bool
    condition_payload: Any
    validator_payload: Any
    action_payload: Any


@dataclass(frozen=True, slots=True)
class SlaPolicyRow:
    sla_definition_id: UUID
    sla_code: str
    sla_name: str
    metric_code: str
    project_key: str
    project_name: str
    active_flag: bool
    goal_count: int
    running_cycle_count: int
    breached_cycle_count: int


@dataclass(frozen=True, slots=True)
class SlaVersionRow:
    sla_definition_version_id: UUID
    version_number: int
    version_status: str
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class SlaPolicyDetailRow:
    sla_definition_id: UUID
    sla_code: str
    sla_name: str
    metric_code: str
    description: str | None
    project_key: str
    project_name: str
    active_flag: bool
    start_condition_payload: Any
    pause_condition_payload: Any
    stop_condition_payload: Any
    versions: tuple[SlaVersionRow, ...]
    pending_count: int
    running_count: int
    paused_count: int
    completed_count: int
    breached_count: int
    cancelled_count: int


@dataclass(frozen=True, slots=True)
class SlaGoalRow:
    sla_goal_id: UUID
    goal_name: str
    priority_order: int
    active_flag: bool
    version_number: int | None
    version_status: str | None
    target_minutes: int | None
    warning_minutes: int | None
    match_condition_payload: Any
    calendar_code: str | None
    calendar_name: str | None


@dataclass(frozen=True, slots=True)
class CalendarSummaryRow:
    calendar_id: UUID
    calendar_code: str
    calendar_name: str
    timezone_name: str
    twenty_four_seven_flag: bool
    active_flag: bool
    current_version_number: int | None
    current_version_status: str | None
    linked_goal_count: int


@dataclass(frozen=True, slots=True)
class CalendarVersionRow:
    business_calendar_version_id: UUID
    version_number: int
    version_status: str
    timezone_name: str
    twenty_four_seven_flag: bool
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class LinkedGoalRow:
    sla_code: str
    goal_name: str


@dataclass(frozen=True, slots=True)
class CalendarDetailRow:
    calendar_id: UUID
    calendar_code: str
    calendar_name: str
    timezone_name: str
    twenty_four_seven_flag: bool
    active_flag: bool
    displayed_version_id: UUID | None
    displayed_version_number: int | None
    displayed_version_status: str | None
    versions: tuple[CalendarVersionRow, ...]
    linked_goals: tuple[LinkedGoalRow, ...]


@dataclass(frozen=True, slots=True)
class WorkingPeriodRow:
    iso_day_of_week: int
    start_local_time: str
    end_local_time: str


@dataclass(frozen=True, slots=True)
class CalendarExceptionRow:
    exception_date: str
    exception_type: str
    start_local_time: str | None
    end_local_time: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class RequestTypeSummaryRow:
    request_type_id: UUID
    request_type_code: str
    request_type_name: str
    portal_group: str | None
    project_key: str
    project_name: str
    work_type_code: str
    workflow_code: str
    workflow_name: str
    employee_visible_flag: bool
    active_flag: bool
    display_order: int
    current_version_number: int | None
    current_version_status: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RequestTypeVersionRow:
    request_type_version_id: UUID
    version_number: int
    version_status: str
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class RequestTypeDetailRow:
    request_type_id: UUID
    request_type_code: str
    request_type_name: str
    portal_description: str | None
    portal_group: str | None
    icon_name: str | None
    project_key: str
    project_name: str
    work_type_code: str
    workflow_id: UUID
    workflow_code: str
    workflow_name: str
    employee_visible_flag: bool
    active_flag: bool
    display_order: int
    displayed_version_id: UUID | None
    displayed_version_number: int | None
    displayed_version_status: str | None
    versions: tuple[RequestTypeVersionRow, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FormFieldOptionRow:
    option_code: str
    option_label: str
    display_order: int
    active_flag: bool


@dataclass(frozen=True, slots=True)
class FormFieldRow:
    field_code: str
    label: str
    data_type: str
    required_flag: bool
    hidden_flag: bool
    display_order: int
    help_text: str | None
    condition_payload: Any
    options: tuple[FormFieldOptionRow, ...]


@dataclass(frozen=True, slots=True)
class RequestTypeLockRow:
    request_type_id: UUID
    request_type_name: str
    active_flag: bool
    employee_visible_flag: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RequestTypeVisibilityRow:
    active_flag: bool
    employee_visible_flag: bool
    updated_at: datetime


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def escape_like_pattern(search: str | None) -> str | None:
    """A contains-pattern with LIKE wildcards neutralised, or None when unset."""
    if search is None:
        return None
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _identity_timestamp(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _external_identities(value: object) -> tuple[ExternalIdentityRow, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        ExternalIdentityRow(
            provider_code=str(item["provider_code"]),
            active_flag=bool(item["active_flag"]),
            last_authenticated_at=_identity_timestamp(item.get("last_authenticated_at")),
        )
        for item in value
        if isinstance(item, dict)
    )


def _json_items(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _optional_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) else None


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def overview(self, tenant_id: UUID) -> OverviewCounts:
        row = (await self._session.execute(_OVERVIEW, {"tenant_id": tenant_id})).one()
        return OverviewCounts(
            active_users=int(row.active_users),
            support_groups=int(row.support_groups),
            open_tickets=int(row.open_tickets),
            published_knowledge_documents=int(row.published_knowledge_documents),
        )

    async def audit_events(
        self,
        tenant_id: UUID,
        *,
        resource_type: str | None,
        action_code: str | None,
        outcome_code: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[AuditEventRow, ...]:
        rows = (
            await self._session.execute(
                _AUDIT_EVENTS,
                {
                    "tenant_id": tenant_id,
                    "resource_type": resource_type,
                    "action_code": action_code,
                    "outcome_code": outcome_code,
                    "occurred_from": occurred_from,
                    "occurred_to": occurred_to,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            AuditEventRow(
                id=int(row.audit_event_id),
                actor_id=row.actor_id,
                actor_type=row.actor_type,
                action_code=row.action_code,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                outcome_code=row.outcome_code,
                failure_reason=row.failure_reason,
                change_summary=_mapping(row.change_summary_json),
                correlation_id=row.correlation_id,
                request_id=row.request_id,
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    async def security_events(
        self,
        tenant_id: UUID,
        *,
        event_type: str | None,
        decision_code: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[SecurityEventRow, ...]:
        rows = (
            await self._session.execute(
                _SECURITY_EVENTS,
                {
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "decision_code": decision_code,
                    "occurred_from": occurred_from,
                    "occurred_to": occurred_to,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            SecurityEventRow(
                id=int(row.security_event_id),
                event_type=row.event_type,
                decision_code=row.decision_code,
                user_id=row.user_id,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                details=_mapping(row.event_data_json),
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    async def users(
        self,
        tenant_id: UUID,
        *,
        search: str | None,
        active: bool | None,
        role_code: str | None,
        support_group_id: UUID | None,
        provider_code: str | None,
        limit: int,
        offset: int,
    ) -> tuple[AdminUserRow, ...]:
        rows = (
            await self._session.execute(
                _USERS,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "active": active,
                    "role_code": role_code,
                    "support_group_id": support_group_id,
                    "provider_code": provider_code,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            AdminUserRow(
                user_id=row.user_id,
                display_name=row.display_name,
                email_address=row.email_address,
                active_flag=row.active_flag,
                business_unit_name=row.business_unit_name,
                role_codes=tuple(row.role_codes),
                support_group_names=tuple(row.support_group_names),
                identity_provider_codes=tuple(row.identity_provider_codes),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        )

    async def user_profile(self, tenant_id: UUID, user_id: UUID) -> AdminUserProfileRow | None:
        row = (
            await self._session.execute(_USER_PROFILE, {"tenant_id": tenant_id, "user_id": user_id})
        ).one_or_none()
        if row is None:
            return None
        return AdminUserProfileRow(
            user_id=row.user_id,
            display_name=row.display_name,
            email_address=row.email_address,
            active_flag=row.active_flag,
            external_subject=row.external_subject,
            locale_code=row.locale_code,
            timezone_name=row.timezone_name,
            business_unit_name=row.business_unit_name,
            external_identities=_external_identities(row.external_identities),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def user_roles(self, tenant_id: UUID, user_id: UUID) -> tuple[UserRoleRow, ...]:
        rows = (
            await self._session.execute(_USER_ROLES, {"tenant_id": tenant_id, "user_id": user_id})
        ).all()
        return tuple(
            UserRoleRow(
                role_code=row.role_code,
                role_name=row.role_name,
                active_flag=row.active_flag,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
            )
            for row in rows
        )

    async def user_memberships(
        self, tenant_id: UUID, user_id: UUID
    ) -> tuple[UserMembershipRow, ...]:
        rows = (
            await self._session.execute(
                _USER_MEMBERSHIPS, {"tenant_id": tenant_id, "user_id": user_id}
            )
        ).all()
        return tuple(
            UserMembershipRow(
                support_group_id=row.support_group_id,
                group_name=row.group_name,
                member_role=row.member_role,
                active_flag=row.active_flag,
                joined_at=row.joined_at,
            )
            for row in rows
        )

    async def user_security_events(
        self, tenant_id: UUID, user_id: UUID, *, limit: int
    ) -> tuple[SecurityEventRow, ...]:
        rows = (
            await self._session.execute(
                _USER_SECURITY_EVENTS,
                {"tenant_id": tenant_id, "user_id": user_id, "result_limit": limit},
            )
        ).all()
        return tuple(
            SecurityEventRow(
                id=int(row.security_event_id),
                event_type=row.event_type,
                decision_code=row.decision_code,
                user_id=row.user_id,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                details=_mapping(row.event_data_json),
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    async def roles(
        self, tenant_id: UUID, *, search: str | None, limit: int, offset: int
    ) -> tuple[RoleSummaryRow, ...]:
        rows = (
            await self._session.execute(
                _ROLES,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            RoleSummaryRow(
                role_code=row.role_code,
                role_name=row.role_name,
                description=row.description,
                system_role_flag=row.system_role_flag,
                active_flag=row.active_flag,
                assigned_user_count=int(row.assigned_user_count),
            )
            for row in rows
        )

    async def role(self, role_code: str) -> RoleSummaryRow | None:
        row = (await self._session.execute(_ROLE, {"role_code": role_code})).one_or_none()
        if row is None:
            return None
        return RoleSummaryRow(
            role_code=row.role_code,
            role_name=row.role_name,
            description=row.description,
            system_role_flag=row.system_role_flag,
            active_flag=row.active_flag,
            assigned_user_count=0,
        )

    async def role_assignments(
        self, tenant_id: UUID, role_code: str, *, limit: int, offset: int
    ) -> tuple[RoleAssignmentRow, ...]:
        rows = (
            await self._session.execute(
                _ROLE_ASSIGNMENTS,
                {
                    "tenant_id": tenant_id,
                    "role_code": role_code,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            RoleAssignmentRow(
                user_id=row.user_id,
                display_name=row.display_name,
                email_address=row.email_address,
                active_flag=row.active_flag,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
            )
            for row in rows
        )

    async def queues(
        self,
        tenant_id: UUID,
        *,
        search: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[QueueSummaryRow, ...]:
        rows = (
            await self._session.execute(
                _QUEUES,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "active": active,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            QueueSummaryRow(
                support_group_id=row.support_group_id,
                group_code=row.group_code,
                group_name=row.group_name,
                contact_email=row.email_address,
                assignment_method=row.assignment_method,
                active_flag=row.active_flag,
                member_count=int(row.member_count),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        )

    async def queue(self, tenant_id: UUID, support_group_id: UUID) -> QueueDetailRow | None:
        row = (
            await self._session.execute(
                _QUEUE, {"tenant_id": tenant_id, "support_group_id": support_group_id}
            )
        ).one_or_none()
        if row is None:
            return None
        return QueueDetailRow(
            support_group_id=row.support_group_id,
            group_code=row.group_code,
            group_name=row.group_name,
            contact_email=row.email_address,
            assignment_method=row.assignment_method,
            active_flag=row.active_flag,
            manager_display_name=row.manager_display_name,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def queue_members(
        self, tenant_id: UUID, support_group_id: UUID
    ) -> tuple[QueueMemberRow, ...]:
        rows = (
            await self._session.execute(
                _QUEUE_MEMBERS, {"tenant_id": tenant_id, "support_group_id": support_group_id}
            )
        ).all()
        return tuple(
            QueueMemberRow(
                user_id=row.user_id,
                display_name=row.display_name,
                member_role=row.member_role,
                active_flag=row.active_flag,
                joined_at=row.joined_at,
            )
            for row in rows
        )

    async def ticket_views(
        self,
        tenant_id: UUID,
        *,
        owner_group_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[TicketViewRow, ...]:
        rows = (
            await self._session.execute(
                _TICKET_VIEWS,
                {
                    "tenant_id": tenant_id,
                    "owner_group_id": owner_group_id,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            TicketViewRow(
                queue_id=row.queue_id,
                queue_name=row.queue_name,
                description=row.description,
                project_code=row.project_code,
                visibility=row.visibility_type,
                display_order=int(row.display_order),
                version_status=row.version_status,
                active_flag=row.active_flag,
            )
            for row in rows
        )

    async def lock_tenant_identity(self, tenant_id: UUID) -> None:
        await self._session.execute(_LOCK_TENANT_IDENTITY, {"tenant_id": tenant_id})

    async def user_for_update(self, tenant_id: UUID, user_id: UUID) -> UserLockRow | None:
        row = (
            await self._session.execute(
                _USER_FOR_UPDATE, {"tenant_id": tenant_id, "user_id": user_id}
            )
        ).one_or_none()
        if row is None:
            return None
        return UserLockRow(
            user_id=row.user_id,
            display_name=row.display_name,
            active_flag=row.active_flag,
            updated_at=row.updated_at,
        )

    async def active_admin_count(
        self, tenant_id: UUID, *, admin_role_code: str, excluded_user_id: UUID
    ) -> int:
        row = (
            await self._session.execute(
                _ACTIVE_ADMIN_COUNT,
                {
                    "tenant_id": tenant_id,
                    "role_code": admin_role_code,
                    "excluded_user_id": excluded_user_id,
                },
            )
        ).one()
        return int(row.admin_count)

    async def set_user_active(self, tenant_id: UUID, user_id: UUID, *, active: bool) -> datetime:
        row = (
            await self._session.execute(
                _SET_USER_ACTIVE,
                {"tenant_id": tenant_id, "user_id": user_id, "active": active},
            )
        ).one()
        return row.updated_at  # type: ignore[no-any-return]

    async def active_role_definition(self, role_code: str) -> bool:
        row = (
            await self._session.execute(_ACTIVE_ROLE_DEFINITION, {"role_code": role_code})
        ).one_or_none()
        return row is not None

    async def active_role_assignment(
        self, tenant_id: UUID, user_id: UUID, role_code: str
    ) -> datetime | None:
        row = (
            await self._session.execute(
                _ACTIVE_ASSIGNMENT,
                {"tenant_id": tenant_id, "user_id": user_id, "role_code": role_code},
            )
        ).one_or_none()
        return None if row is None else row.valid_from

    async def insert_role_assignment(
        self, tenant_id: UUID, user_id: UUID, role_code: str, *, granted_by: UUID | None
    ) -> datetime:
        row = (
            await self._session.execute(
                _INSERT_ASSIGNMENT,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "role_code": role_code,
                    "granted_by": granted_by,
                },
            )
        ).one()
        return row.valid_from  # type: ignore[no-any-return]

    async def close_role_assignments(self, tenant_id: UUID, user_id: UUID, role_code: str) -> int:
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                _CLOSE_ASSIGNMENTS,
                {"tenant_id": tenant_id, "user_id": user_id, "role_code": role_code},
            ),
        )
        return int(result.rowcount or 0)

    async def queue_reference(self, tenant_id: UUID, support_group_id: UUID) -> QueueRefRow | None:
        row = (
            await self._session.execute(
                _QUEUE_FOR_TENANT,
                {"tenant_id": tenant_id, "support_group_id": support_group_id},
            )
        ).one_or_none()
        if row is None:
            return None
        return QueueRefRow(support_group_id=row.support_group_id, group_name=row.group_name)

    async def membership_for_update(
        self, support_group_id: UUID, user_id: UUID
    ) -> MembershipStateRow | None:
        row = (
            await self._session.execute(
                _MEMBERSHIP_FOR_UPDATE,
                {"support_group_id": support_group_id, "user_id": user_id},
            )
        ).one_or_none()
        if row is None:
            return None
        return MembershipStateRow(member_role=row.member_role, active_flag=row.active_flag)

    async def upsert_queue_member(
        self, support_group_id: UUID, user_id: UUID, *, member_role: str
    ) -> None:
        await self._session.execute(
            _UPSERT_MEMBER,
            {
                "support_group_id": support_group_id,
                "user_id": user_id,
                "member_role": member_role,
            },
        )

    async def deactivate_queue_member(self, support_group_id: UUID, user_id: UUID) -> int:
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                _DEACTIVATE_MEMBER,
                {"support_group_id": support_group_id, "user_id": user_id},
            ),
        )
        return int(result.rowcount or 0)

    async def record_admin_action(
        self,
        tenant_id: UUID,
        *,
        actor_id: UUID | None,
        action_code: str,
        resource_type: str,
        resource_id: str,
        change_summary: dict[str, Any],
    ) -> None:
        await self._session.execute(
            _INSERT_ADMIN_AUDIT_EVENT,
            {
                "tenant_id": tenant_id,
                "actor_id": str(actor_id) if actor_id else None,
                "action_code": action_code,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "change_summary": json.dumps(change_summary, separators=(",", ":")),
            },
        )

    async def workflows(
        self,
        tenant_id: UUID,
        *,
        search: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[WorkflowSummaryRow, ...]:
        rows = (
            await self._session.execute(
                _WORKFLOWS,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "active": active,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            WorkflowSummaryRow(
                workflow_id=row.workflow_id,
                workflow_code=row.workflow_code,
                workflow_name=row.workflow_name,
                description=row.description,
                active_flag=row.active_flag,
                current_version_number=row.current_version_number,
                current_version_status=row.current_version_status,
                status_count=int(row.status_count),
                transition_count=int(row.transition_count),
                request_type_count=int(row.request_type_count),
                ticket_count=int(row.ticket_count),
                created_at=row.created_at,
            )
            for row in rows
        )

    async def workflow(self, tenant_id: UUID, workflow_id: UUID) -> WorkflowDetailRow | None:
        row = (
            await self._session.execute(
                _WORKFLOW, {"tenant_id": tenant_id, "workflow_id": workflow_id}
            )
        ).one_or_none()
        if row is None:
            return None
        versions = tuple(
            WorkflowVersionRow(
                workflow_version_id=UUID(str(item["workflow_version_id"])),
                version_number=int(item["version_number"]),
                version_status=str(item["version_status"]),
                effective_from=_identity_timestamp(item.get("effective_from")),
                effective_to=_identity_timestamp(item.get("effective_to")),
                published_at=_identity_timestamp(item.get("published_at")),
                published_by_display_name=_optional_str(item.get("published_by_display_name")),
                created_at=_identity_timestamp(item.get("created_at")) or row.created_at,
                ticket_count=int(item.get("ticket_count") or 0),
            )
            for item in _json_items(row.versions)
        )
        request_types = tuple(
            WorkflowRequestTypeRow(
                request_type_id=UUID(str(item["request_type_id"])),
                request_type_code=str(item["request_type_code"]),
                request_type_name=str(item["request_type_name"]),
                active_flag=bool(item["active_flag"]),
                employee_visible_flag=bool(item["employee_visible_flag"]),
            )
            for item in _json_items(row.request_types)
        )
        return WorkflowDetailRow(
            workflow_id=row.workflow_id,
            workflow_code=row.workflow_code,
            workflow_name=row.workflow_name,
            description=row.description,
            active_flag=row.active_flag,
            created_at=row.created_at,
            displayed_version_id=row.displayed_version_id,
            displayed_version_number=row.displayed_version_number,
            displayed_version_status=row.displayed_version_status,
            versions=versions,
            request_types=request_types,
        )

    async def workflow_statuses(self, workflow_version_id: UUID) -> tuple[WorkflowStatusRow, ...]:
        rows = (
            await self._session.execute(
                _WORKFLOW_STATUSES, {"workflow_version_id": workflow_version_id}
            )
        ).all()
        return tuple(
            WorkflowStatusRow(
                status_id=row.status_id,
                status_code=row.status_code,
                status_name=row.status_name,
                status_category=row.status_category,
                initial_flag=row.initial_flag,
                terminal_flag=row.terminal_flag,
                customer_visible_name=row.customer_visible_name,
                display_order=int(row.display_order),
            )
            for row in rows
        )

    async def workflow_transitions(
        self, workflow_version_id: UUID
    ) -> tuple[WorkflowTransitionRow, ...]:
        rows = (
            await self._session.execute(
                _WORKFLOW_TRANSITIONS, {"workflow_version_id": workflow_version_id}
            )
        ).all()
        return tuple(
            WorkflowTransitionRow(
                transition_id=row.transition_id,
                transition_code=row.transition_code,
                transition_name=row.transition_name,
                from_status_code=row.from_status_code,
                from_status_name=row.from_status_name,
                to_status_code=row.to_status_code,
                to_status_name=row.to_status_name,
                display_order=int(row.display_order),
                active_flag=row.active_flag,
                condition_payload=row.condition_json,
                validator_payload=row.validator_json,
                action_payload=row.action_json,
            )
            for row in rows
        )

    async def sla_policies(
        self,
        tenant_id: UUID,
        *,
        search: str | None,
        active: bool | None,
        project_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[SlaPolicyRow, ...]:
        rows = (
            await self._session.execute(
                _SLA_POLICIES,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "active": active,
                    "project_id": project_id,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            SlaPolicyRow(
                sla_definition_id=row.sla_definition_id,
                sla_code=row.sla_code,
                sla_name=row.sla_name,
                metric_code=row.metric_code,
                project_key=row.project_key,
                project_name=row.project_name,
                active_flag=row.active_flag,
                goal_count=int(row.goal_count),
                running_cycle_count=int(row.running_cycle_count),
                breached_cycle_count=int(row.breached_cycle_count),
            )
            for row in rows
        )

    async def sla_policy(
        self, tenant_id: UUID, sla_definition_id: UUID
    ) -> SlaPolicyDetailRow | None:
        row = (
            await self._session.execute(
                _SLA_POLICY,
                {"tenant_id": tenant_id, "sla_definition_id": sla_definition_id},
            )
        ).one_or_none()
        if row is None:
            return None
        versions = tuple(
            SlaVersionRow(
                sla_definition_version_id=UUID(str(item["sla_definition_version_id"])),
                version_number=int(item["version_number"]),
                version_status=str(item["version_status"]),
                effective_from=_identity_timestamp(item.get("effective_from")),
                effective_to=_identity_timestamp(item.get("effective_to")),
                published_at=_identity_timestamp(item.get("published_at")),
            )
            for item in _json_items(row.versions)
        )
        return SlaPolicyDetailRow(
            sla_definition_id=row.sla_definition_id,
            sla_code=row.sla_code,
            sla_name=row.sla_name,
            metric_code=row.metric_code,
            description=row.description,
            project_key=row.project_key,
            project_name=row.project_name,
            active_flag=row.active_flag,
            start_condition_payload=row.start_condition_json,
            pause_condition_payload=row.pause_condition_json,
            stop_condition_payload=row.stop_condition_json,
            versions=versions,
            pending_count=int(row.pending_count),
            running_count=int(row.running_count),
            paused_count=int(row.paused_count),
            completed_count=int(row.completed_count),
            breached_count=int(row.breached_count),
            cancelled_count=int(row.cancelled_count),
        )

    async def sla_goals(self, sla_definition_id: UUID) -> tuple[SlaGoalRow, ...]:
        rows = (
            await self._session.execute(_SLA_GOALS, {"sla_definition_id": sla_definition_id})
        ).all()
        return tuple(
            SlaGoalRow(
                sla_goal_id=row.sla_goal_id,
                goal_name=row.goal_name,
                priority_order=int(row.priority_order),
                active_flag=row.active_flag,
                version_number=_optional_int(row.version_number),
                version_status=row.version_status,
                target_minutes=_optional_int(row.target_minutes),
                warning_minutes=_optional_int(row.warning_minutes),
                match_condition_payload=row.match_condition_json,
                calendar_code=row.calendar_code,
                calendar_name=row.calendar_name,
            )
            for row in rows
        )

    async def calendars(
        self,
        tenant_id: UUID,
        *,
        search: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[CalendarSummaryRow, ...]:
        rows = (
            await self._session.execute(
                _CALENDARS,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "active": active,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            CalendarSummaryRow(
                calendar_id=row.calendar_id,
                calendar_code=row.calendar_code,
                calendar_name=row.calendar_name,
                timezone_name=row.timezone_name,
                twenty_four_seven_flag=row.twenty_four_seven_flag,
                active_flag=row.active_flag,
                current_version_number=row.current_version_number,
                current_version_status=row.current_version_status,
                linked_goal_count=int(row.linked_goal_count),
            )
            for row in rows
        )

    async def calendar(self, tenant_id: UUID, calendar_id: UUID) -> CalendarDetailRow | None:
        row = (
            await self._session.execute(
                _CALENDAR, {"tenant_id": tenant_id, "calendar_id": calendar_id}
            )
        ).one_or_none()
        if row is None:
            return None
        versions = tuple(
            CalendarVersionRow(
                business_calendar_version_id=UUID(str(item["business_calendar_version_id"])),
                version_number=int(item["version_number"]),
                version_status=str(item["version_status"]),
                timezone_name=str(item["timezone_name"]),
                twenty_four_seven_flag=bool(item["twenty_four_seven_flag"]),
                effective_from=_identity_timestamp(item.get("effective_from")),
                effective_to=_identity_timestamp(item.get("effective_to")),
                published_at=_identity_timestamp(item.get("published_at")),
            )
            for item in _json_items(row.versions)
        )
        linked_goals = tuple(
            LinkedGoalRow(
                sla_code=str(item["sla_code"]),
                goal_name=str(item["goal_name"]),
            )
            for item in _json_items(row.linked_goals)
        )
        return CalendarDetailRow(
            calendar_id=row.calendar_id,
            calendar_code=row.calendar_code,
            calendar_name=row.calendar_name,
            timezone_name=row.timezone_name,
            twenty_four_seven_flag=row.twenty_four_seven_flag,
            active_flag=row.active_flag,
            displayed_version_id=row.displayed_version_id,
            displayed_version_number=row.displayed_version_number,
            displayed_version_status=row.displayed_version_status,
            versions=versions,
            linked_goals=linked_goals,
        )

    async def calendar_working_periods(
        self, business_calendar_version_id: UUID
    ) -> tuple[WorkingPeriodRow, ...]:
        rows = (
            await self._session.execute(
                _CALENDAR_WORKING_PERIODS,
                {"business_calendar_version_id": business_calendar_version_id},
            )
        ).all()
        return tuple(
            WorkingPeriodRow(
                iso_day_of_week=int(row.iso_day_of_week),
                start_local_time=row.start_local_time.isoformat(timespec="minutes"),
                end_local_time=row.end_local_time.isoformat(timespec="minutes"),
            )
            for row in rows
        )

    async def calendar_exceptions(
        self, business_calendar_version_id: UUID
    ) -> tuple[CalendarExceptionRow, ...]:
        rows = (
            await self._session.execute(
                _CALENDAR_EXCEPTIONS,
                {"business_calendar_version_id": business_calendar_version_id},
            )
        ).all()
        return tuple(
            CalendarExceptionRow(
                exception_date=row.exception_date.isoformat(),
                exception_type=row.exception_type,
                start_local_time=(
                    row.start_local_time.isoformat(timespec="minutes")
                    if row.start_local_time is not None
                    else None
                ),
                end_local_time=(
                    row.end_local_time.isoformat(timespec="minutes")
                    if row.end_local_time is not None
                    else None
                ),
                description=row.description,
            )
            for row in rows
        )

    async def request_types(
        self,
        tenant_id: UUID,
        *,
        search: str | None,
        active: bool | None,
        project_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[RequestTypeSummaryRow, ...]:
        rows = (
            await self._session.execute(
                _REQUEST_TYPES,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "active": active,
                    "project_id": project_id,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            RequestTypeSummaryRow(
                request_type_id=row.request_type_id,
                request_type_code=row.request_type_code,
                request_type_name=row.request_type_name,
                portal_group=row.portal_group,
                project_key=row.project_key,
                project_name=row.project_name,
                work_type_code=row.work_type_code,
                workflow_code=row.workflow_code,
                workflow_name=row.workflow_name,
                employee_visible_flag=row.employee_visible_flag,
                active_flag=row.active_flag,
                display_order=int(row.display_order),
                current_version_number=row.current_version_number,
                current_version_status=row.current_version_status,
                updated_at=row.updated_at,
            )
            for row in rows
        )

    async def request_type(
        self, tenant_id: UUID, request_type_id: UUID
    ) -> RequestTypeDetailRow | None:
        row = (
            await self._session.execute(
                _REQUEST_TYPE,
                {"tenant_id": tenant_id, "request_type_id": request_type_id},
            )
        ).one_or_none()
        if row is None:
            return None
        versions = tuple(
            RequestTypeVersionRow(
                request_type_version_id=UUID(str(item["request_type_version_id"])),
                version_number=int(item["version_number"]),
                version_status=str(item["version_status"]),
                effective_from=_identity_timestamp(item.get("effective_from")),
                effective_to=_identity_timestamp(item.get("effective_to")),
                published_at=_identity_timestamp(item.get("published_at")),
            )
            for item in _json_items(row.versions)
        )
        return RequestTypeDetailRow(
            request_type_id=row.request_type_id,
            request_type_code=row.request_type_code,
            request_type_name=row.request_type_name,
            portal_description=row.portal_description,
            portal_group=row.portal_group,
            icon_name=row.icon_name,
            project_key=row.project_key,
            project_name=row.project_name,
            work_type_code=row.work_type_code,
            workflow_id=row.workflow_id,
            workflow_code=row.workflow_code,
            workflow_name=row.workflow_name,
            employee_visible_flag=row.employee_visible_flag,
            active_flag=row.active_flag,
            display_order=int(row.display_order),
            displayed_version_id=row.displayed_version_id,
            displayed_version_number=row.displayed_version_number,
            displayed_version_status=row.displayed_version_status,
            versions=versions,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def request_type_form_fields(
        self, tenant_id: UUID, request_type_version_id: UUID
    ) -> tuple[FormFieldRow, ...]:
        rows = (
            await self._session.execute(
                _REQUEST_TYPE_FORM_FIELDS,
                {
                    "tenant_id": tenant_id,
                    "request_type_version_id": request_type_version_id,
                },
            )
        ).all()
        return tuple(
            FormFieldRow(
                field_code=row.field_code,
                label=row.label,
                data_type=row.data_type,
                required_flag=row.required_flag,
                hidden_flag=row.hidden_flag,
                display_order=int(row.display_order),
                help_text=row.help_text,
                condition_payload=row.condition_json,
                options=tuple(
                    FormFieldOptionRow(
                        option_code=str(item["option_code"]),
                        option_label=str(item["option_label"]),
                        display_order=int(item["display_order"]),
                        active_flag=bool(item["active_flag"]),
                    )
                    for item in _json_items(row.options)
                ),
            )
            for row in rows
        )

    async def request_type_for_update(
        self, tenant_id: UUID, request_type_id: UUID
    ) -> RequestTypeLockRow | None:
        row = (
            await self._session.execute(
                _REQUEST_TYPE_FOR_UPDATE,
                {"tenant_id": tenant_id, "request_type_id": request_type_id},
            )
        ).one_or_none()
        if row is None:
            return None
        return RequestTypeLockRow(
            request_type_id=row.request_type_id,
            request_type_name=row.request_type_name,
            active_flag=row.active_flag,
            employee_visible_flag=row.employee_visible_flag,
            updated_at=row.updated_at,
        )

    async def set_request_type_visibility(
        self,
        tenant_id: UUID,
        request_type_id: UUID,
        *,
        active: bool,
        employee_visible: bool,
    ) -> RequestTypeVisibilityRow:
        row = (
            await self._session.execute(
                _SET_REQUEST_TYPE_VISIBILITY,
                {
                    "tenant_id": tenant_id,
                    "request_type_id": request_type_id,
                    "active": active,
                    "employee_visible": employee_visible,
                },
            )
        ).one()
        return RequestTypeVisibilityRow(
            active_flag=row.active_flag,
            employee_visible_flag=row.employee_visible_flag,
            updated_at=row.updated_at,
        )
