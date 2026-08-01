\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE ai.conversation (
    conversation_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    conversation_type varchar(30) NOT NULL,
    user_id           uuid NOT NULL REFERENCES identity.app_user(user_id),
    ticket_id         uuid REFERENCES itsm.ticket(ticket_id),
    status_code       varchar(20) NOT NULL DEFAULT 'OPEN',
    started_at        timestamptz NOT NULL DEFAULT now(),
    ended_at          timestamptz,
    metadata_json     jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ai_conversation_type_ck CHECK (
        conversation_type IN ('EMPLOYEE_HELPDESK','ANALYST_COPILOT','KNOWLEDGE_AUTHORING','ADMIN_ASSISTANT')
    ),
    CONSTRAINT ai_conversation_status_ck CHECK (
        status_code IN ('OPEN','CLOSED','ARCHIVED')
    )
);

ALTER TABLE itsm.ticket
ADD CONSTRAINT ticket_source_conversation_fk
FOREIGN KEY (source_conversation_id) REFERENCES ai.conversation(conversation_id);

CREATE TABLE ai.message (
    message_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id   uuid NOT NULL REFERENCES ai.conversation(conversation_id) ON DELETE CASCADE,
    role_code         varchar(20) NOT NULL,
    content_text      text,
    content_json      jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    token_count       integer,
    CONSTRAINT ai_message_role_ck CHECK (
        role_code IN ('SYSTEM','USER','ASSISTANT','TOOL')
    )
);

CREATE TABLE ai.agent_run (
    agent_run_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    conversation_id   uuid NOT NULL REFERENCES ai.conversation(conversation_id) ON DELETE CASCADE,
    provider_name     varchar(100) NOT NULL,
    model_name        varchar(200) NOT NULL,
    instruction_version varchar(100),
    run_status        varchar(30) NOT NULL,
    started_at        timestamptz NOT NULL DEFAULT now(),
    completed_at      timestamptz,
    input_tokens      integer,
    output_tokens     integer,
    latency_ms        integer,
    estimated_cost    numeric(18,8),
    error_code        varchar(100),
    error_message     text,
    CONSTRAINT ai_run_status_ck CHECK (
        run_status IN ('RUNNING','COMPLETED','FAILED','CANCELLED','REQUIRES_APPROVAL')
    )
);

CREATE TABLE ai.tool_call (
    tool_call_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id      uuid NOT NULL REFERENCES ai.agent_run(agent_run_id) ON DELETE CASCADE,
    tool_name         varchar(150) NOT NULL,
    request_json      jsonb NOT NULL,
    response_json     jsonb,
    authorization_decision varchar(30) NOT NULL DEFAULT 'PENDING',
    execution_status  varchar(30) NOT NULL DEFAULT 'PENDING',
    requested_at      timestamptz NOT NULL DEFAULT now(),
    completed_at      timestamptz,
    approved_by       uuid REFERENCES identity.app_user(user_id),
    CONSTRAINT ai_tool_auth_ck CHECK (
        authorization_decision IN ('PENDING','ALLOWED','DENIED','HUMAN_APPROVAL_REQUIRED')
    ),
    CONSTRAINT ai_tool_execution_ck CHECK (
        execution_status IN ('PENDING','RUNNING','COMPLETED','FAILED','SKIPPED')
    )
);

CREATE TABLE ai.retrieval_evidence (
    retrieval_evidence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id      uuid NOT NULL REFERENCES ai.agent_run(agent_run_id) ON DELETE CASCADE,
    chunk_id          uuid REFERENCES kb.document_chunk(chunk_id),
    ticket_id         uuid REFERENCES itsm.ticket(ticket_id),
    source_type       varchar(40) NOT NULL,
    semantic_score    numeric(8,6),
    lexical_score     numeric(8,6),
    rerank_score      numeric(8,6),
    citation_label    varchar(300),
    selected_flag     boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT retrieval_source_type_ck CHECK (
        source_type IN ('KNOWLEDGE_CHUNK','HISTORICAL_TICKET','TOOL_RESULT','ORACLE_DOCUMENTATION')
    )
);

CREATE TABLE ai.feedback (
    feedback_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES identity.tenant(tenant_id),
    conversation_id   uuid REFERENCES ai.conversation(conversation_id),
    agent_run_id      uuid REFERENCES ai.agent_run(agent_run_id),
    user_id           uuid REFERENCES identity.app_user(user_id),
    feedback_type     varchar(30) NOT NULL,
    rating_value      integer,
    comment_text      text,
    resolved_issue_flag boolean,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_feedback_type_ck CHECK (
        feedback_type IN ('USER_RATING','ANALYST_ACCEPTANCE','RESOLUTION_OUTCOME','SAFETY_REVIEW','QUALITY_REVIEW')
    ),
    CONSTRAINT ai_feedback_rating_ck CHECK (
        rating_value IS NULL OR rating_value BETWEEN 1 AND 5
    )
);

CREATE TABLE audit.security_event (
    security_event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id         uuid REFERENCES identity.tenant(tenant_id),
    user_id           uuid REFERENCES identity.app_user(user_id),
    event_type        varchar(100) NOT NULL,
    resource_type     varchar(100),
    resource_id       varchar(200),
    decision_code     varchar(30),
    client_ip         inet,
    user_agent        text,
    event_data_json   jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE integration.outbox_event (
    outbox_event_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid REFERENCES identity.tenant(tenant_id),
    aggregate_type    varchar(100) NOT NULL,
    aggregate_id      varchar(200) NOT NULL,
    event_type        varchar(100) NOT NULL,
    payload_json      jsonb NOT NULL,
    status_code       varchar(20) NOT NULL DEFAULT 'PENDING',
    available_at      timestamptz NOT NULL DEFAULT now(),
    locked_at         timestamptz,
    locked_by         varchar(200),
    processed_at      timestamptz,
    retry_count       integer NOT NULL DEFAULT 0,
    last_error        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT outbox_status_ck CHECK (
        status_code IN ('PENDING','PROCESSING','PROCESSED','FAILED','DEAD_LETTER')
    )
);

CREATE INDEX outbox_pending_ix
ON integration.outbox_event (available_at, created_at)
WHERE status_code IN ('PENDING','FAILED');

CREATE INDEX ai_conversation_user_ix
ON ai.conversation (tenant_id, user_id, started_at DESC);

CREATE INDEX ai_retrieval_run_ix
ON ai.retrieval_evidence (agent_run_id, rerank_score DESC);

CREATE INDEX audit_security_event_lookup_ix
ON audit.security_event (tenant_id, occurred_at DESC, event_type);

COMMIT;
