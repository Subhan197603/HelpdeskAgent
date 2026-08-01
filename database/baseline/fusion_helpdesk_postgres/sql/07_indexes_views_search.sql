\set ON_ERROR_STOP on

BEGIN;

CREATE INDEX ticket_group_status_priority_ix
ON itsm.ticket (tenant_id, assignment_group_id, status_id, priority_code, created_at);

CREATE INDEX ticket_assignee_status_ix
ON itsm.ticket (tenant_id, assignee_user_id, status_id, updated_at DESC);

CREATE INDEX ticket_service_created_ix
ON itsm.ticket (tenant_id, service_node_id, created_at DESC);

CREATE INDEX ticket_reporter_created_ix
ON itsm.ticket (tenant_id, reporter_user_id, created_at DESC);

CREATE INDEX ticket_unassigned_ix
ON itsm.ticket (tenant_id, project_id, priority_code, created_at)
WHERE assignment_group_id IS NULL;

CREATE INDEX ticket_event_ticket_time_ix
ON itsm.ticket_event (ticket_id, created_at, event_id);

CREATE INDEX ticket_comment_ticket_time_ix
ON itsm.ticket_comment (ticket_id, created_at);

CREATE INDEX ticket_sla_open_target_ix
ON itsm.ticket_sla (tenant_id, target_at)
WHERE state_code IN ('RUNNING','PAUSED');

CREATE INDEX ticket_approval_pending_ix
ON itsm.ticket_approval (tenant_id, requested_at)
WHERE approval_status = 'PENDING';

CREATE OR REPLACE VIEW itsm.v_ticket_workspace AS
SELECT
    t.ticket_id,
    t.tenant_id,
    t.ticket_key,
    t.summary,
    wt.work_type_code,
    rt.request_type_name,
    ws.status_code,
    ws.status_name,
    ws.status_category,
    t.priority_code,
    t.assignment_group_id,
    sg.group_name AS assignment_group_name,
    t.assignee_user_id,
    au.display_name AS assignee_name,
    t.reporter_user_id,
    ru.display_name AS reporter_name,
    t.service_node_id,
    sn.node_name AS service_name,
    t.environment_code,
    t.created_at,
    t.updated_at,
    t.first_response_at,
    t.resolved_at,
    MIN(ts.target_at) FILTER (WHERE ts.state_code IN ('RUNNING','PAUSED')) AS next_sla_target,
    BOOL_OR(ts.state_code = 'BREACHED') AS has_sla_breach
FROM itsm.ticket t
JOIN config.work_type wt ON wt.work_type_id = t.work_type_id
JOIN config.request_type rt ON rt.request_type_id = t.request_type_id
JOIN config.workflow_status ws ON ws.status_id = t.status_id
LEFT JOIN identity.support_group sg ON sg.support_group_id = t.assignment_group_id
LEFT JOIN identity.app_user au ON au.user_id = t.assignee_user_id
JOIN identity.app_user ru ON ru.user_id = t.reporter_user_id
LEFT JOIN config.service_node sn ON sn.service_node_id = t.service_node_id
LEFT JOIN itsm.ticket_sla ts ON ts.ticket_id = t.ticket_id
GROUP BY
    t.ticket_id, wt.work_type_code, rt.request_type_name,
    ws.status_code, ws.status_name, ws.status_category,
    sg.group_name, au.display_name, ru.display_name, sn.node_name;

CREATE OR REPLACE VIEW kb.v_active_document_chunk AS
SELECT
    c.chunk_id,
    c.document_version_id,
    d.document_id,
    d.tenant_id,
    d.document_title,
    d.document_type,
    d.audience_code,
    d.security_classification,
    d.canonical_url,
    d.release_id,
    d.product_node_id,
    c.heading_path,
    c.chapter_title,
    c.section_title,
    c.section_anchor,
    c.page_number,
    c.content_text,
    c.search_vector,
    r.release_family,
    r.release_code,
    pn.product_code,
    pn.product_name,
    s.source_type,
    s.source_name
FROM kb.document_chunk c
JOIN kb.document_version dv
  ON dv.document_version_id = c.document_version_id
 AND dv.current_version_flag
 AND dv.validation_status IN ('PASSED','WARNING')
JOIN kb.document d
  ON d.document_id = dv.document_id
 AND d.active_flag
 AND d.approval_status = 'APPROVED'
 AND (d.effective_from IS NULL OR d.effective_from <= CURRENT_DATE)
 AND (d.effective_to IS NULL OR d.effective_to >= CURRENT_DATE)
JOIN kb.source s ON s.source_id = d.source_id AND s.active_flag
LEFT JOIN kb.release r ON r.release_id = d.release_id
LEFT JOIN kb.product_node pn ON pn.product_node_id = d.product_node_id;

CREATE OR REPLACE FUNCTION kb.search_chunks_1536(
    p_tenant_id uuid,
    p_query text,
    p_query_embedding vector(1536),
    p_limit integer DEFAULT 12,
    p_release_codes text[] DEFAULT NULL,
    p_audience_codes text[] DEFAULT ARRAY['EMPLOYEE','ALL'],
    p_security_levels text[] DEFAULT ARRAY['PUBLIC','INTERNAL']
)
RETURNS TABLE (
    chunk_id uuid,
    document_id uuid,
    document_title text,
    heading_path text,
    content_text text,
    canonical_url text,
    release_code varchar,
    product_code varchar,
    source_type varchar,
    lexical_score real,
    semantic_score real,
    combined_score real
)
LANGUAGE sql
STABLE
AS $$
WITH q AS (
    SELECT websearch_to_tsquery('english', p_query) AS tsq
), candidates AS (
    SELECT
        v.chunk_id,
        v.document_id,
        v.document_title,
        v.heading_path,
        v.content_text,
        v.canonical_url,
        v.release_code,
        v.product_code,
        v.source_type,
        ts_rank_cd(v.search_vector, q.tsq)::real AS lexical_score,
        (1 - (e.embedding <=> p_query_embedding))::real AS semantic_score
    FROM kb.v_active_document_chunk v
    JOIN kb.chunk_embedding_1536 e ON e.chunk_id = v.chunk_id
    CROSS JOIN q
    WHERE (v.tenant_id IS NULL OR v.tenant_id = p_tenant_id)
      AND (p_release_codes IS NULL OR v.release_code::text = ANY(p_release_codes))
      AND v.audience_code::text = ANY(p_audience_codes)
      AND v.security_classification::text = ANY(p_security_levels)
      AND (
            v.search_vector @@ q.tsq
            OR (e.embedding <=> p_query_embedding) < 0.45
          )
)
SELECT
    c.chunk_id,
    c.document_id,
    c.document_title,
    c.heading_path,
    c.content_text,
    c.canonical_url,
    c.release_code,
    c.product_code,
    c.source_type,
    c.lexical_score,
    c.semantic_score,
    (
        0.40 * c.semantic_score +
        0.35 * LEAST(c.lexical_score, 1.0) +
        0.15 * 1.0 +
        0.10 * CASE c.source_type
                   WHEN 'COMPANY_POLICY' THEN 1.00
                   WHEN 'COMPANY_PROCEDURE' THEN 0.95
                   WHEN 'ORACLE_PUBLIC_DOCUMENTATION' THEN 0.90
                   WHEN 'INTERNAL_KNOWLEDGE' THEN 0.85
                   WHEN 'HISTORICAL_RESOLUTION' THEN 0.80
                   ELSE 0.70
               END
    )::real AS combined_score
FROM candidates c
ORDER BY combined_score DESC
LIMIT GREATEST(1, LEAST(p_limit, 100));
$$;

COMMIT;
