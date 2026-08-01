\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE kb.source (
    source_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid REFERENCES identity.tenant(tenant_id),
    source_code       varchar(80) NOT NULL,
    source_name       varchar(250) NOT NULL,
    source_type       varchar(50) NOT NULL,
    publisher_name    varchar(200),
    base_url          text,
    acquisition_method varchar(40) NOT NULL,
    automated_access_allowed boolean NOT NULL DEFAULT false,
    permission_reference text,
    active_flag       boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, source_code),
    CONSTRAINT kb_source_type_ck CHECK (
        source_type IN (
            'ORACLE_PUBLIC_DOCUMENTATION','COMPANY_POLICY','COMPANY_PROCEDURE',
            'INTERNAL_KNOWLEDGE','HISTORICAL_RESOLUTION','OTHER_EXTERNAL'
        )
    ),
    CONSTRAINT kb_acquisition_method_ck CHECK (
        acquisition_method IN (
            'MANUAL_UPLOAD','APPROVED_DIRECT_DOWNLOAD','API_FEED',
            'REPOSITORY_CONNECTOR','TICKET_PUBLICATION'
        )
    )
);

CREATE TRIGGER kb_source_set_updated_at
BEFORE UPDATE ON kb.source
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE kb.release (
    release_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    release_family    varchar(50) NOT NULL,
    release_code      varchar(40) NOT NULL,
    release_name      varchar(150),
    release_date      date,
    support_status    varchar(30) NOT NULL DEFAULT 'CURRENT',
    effective_from    date,
    effective_to      date,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (release_family, release_code),
    CONSTRAINT kb_release_family_ck CHECK (
        release_family IN (
            'FUSION_APPLICATIONS','FUSION_DATA_INTELLIGENCE',
            'ORACLE_ANALYTICS','COMPANY_DOCUMENT','OTHER'
        )
    ),
    CONSTRAINT kb_release_status_ck CHECK (
        support_status IN ('PLANNED','CURRENT','SUPPORTED','SUPERSEDED','RETIRED')
    )
);

CREATE TABLE kb.product_node (
    product_node_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid REFERENCES identity.tenant(tenant_id),
    parent_product_node_id uuid REFERENCES kb.product_node(product_node_id),
    product_code      varchar(150) NOT NULL,
    product_name      varchar(300) NOT NULL,
    product_level     varchar(40) NOT NULL,
    release_family    varchar(50),
    active_flag       boolean NOT NULL DEFAULT true,
    display_order     integer NOT NULL DEFAULT 0,
    UNIQUE NULLS NOT DISTINCT (tenant_id, product_code),
    CONSTRAINT kb_product_level_ck CHECK (
        product_level IN (
            'SUITE','PRODUCT_FAMILY','PRODUCT','MODULE',
            'BUSINESS_PROCESS','DOCUMENT_COLLECTION'
        )
    )
);

CREATE TABLE kb.document (
    document_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid REFERENCES identity.tenant(tenant_id),
    source_id         uuid NOT NULL REFERENCES kb.source(source_id),
    product_node_id   uuid REFERENCES kb.product_node(product_node_id),
    release_id        uuid REFERENCES kb.release(release_id),
    external_document_key varchar(700),
    document_title    text NOT NULL,
    document_type     varchar(60) NOT NULL,
    audience_code     varchar(30) NOT NULL,
    canonical_url     text,
    language_code     varchar(10) NOT NULL DEFAULT 'en',
    owner_group_id    uuid REFERENCES identity.support_group(support_group_id),
    security_classification varchar(30) NOT NULL DEFAULT 'INTERNAL',
    approval_status   varchar(30) NOT NULL DEFAULT 'DRAFT',
    policy_owner      varchar(250),
    process_owner     varchar(250),
    approved_by       uuid REFERENCES identity.app_user(user_id),
    approved_at       timestamptz,
    next_review_date  date,
    effective_from    date,
    effective_to      date,
    superseded_by_document_id uuid REFERENCES kb.document(document_id),
    active_flag       boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT kb_document_type_ck CHECK (
        document_type IN (
            'USER_GUIDE','IMPLEMENTATION_GUIDE','ADMINISTRATION_GUIDE',
            'SECURITY_GUIDE','API_REFERENCE','TABLES_AND_VIEWS',
            'WHATS_NEW','READINESS','FAQ','POLICY','PROCEDURE',
            'RUNBOOK','KNOWN_ERROR','HISTORICAL_FIX','ROOT_CAUSE_ANALYSIS',
            'KNOWLEDGE_ARTICLE','OTHER'
        )
    ),
    CONSTRAINT kb_document_audience_ck CHECK (
        audience_code IN ('EMPLOYEE','ANALYST','TECHNICAL_SPECIALIST','ADMIN','ALL')
    ),
    CONSTRAINT kb_document_security_ck CHECK (
        security_classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')
    ),
    CONSTRAINT kb_document_approval_ck CHECK (
        approval_status IN ('DRAFT','UNDER_REVIEW','APPROVED','REJECTED','RETIRED')
    )
);

CREATE UNIQUE INDEX kb_document_external_key_ux
ON kb.document(source_id, external_document_key)
WHERE external_document_key IS NOT NULL;

CREATE TRIGGER kb_document_set_updated_at
BEFORE UPDATE ON kb.document
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE kb.document_version (
    document_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id       uuid NOT NULL REFERENCES kb.document(document_id) ON DELETE CASCADE,
    version_number    integer NOT NULL,
    source_version_label varchar(100),
    original_file_uri text NOT NULL,
    normalized_file_uri text,
    content_type      varchar(150) NOT NULL,
    file_size_bytes   bigint,
    sha256_checksum   varchar(64) NOT NULL,
    source_last_modified_at timestamptz,
    acquired_at       timestamptz NOT NULL,
    acquisition_run_id uuid,
    copyright_notice  text,
    parser_name       varchar(100),
    parser_version    varchar(50),
    extraction_status varchar(30) NOT NULL DEFAULT 'PENDING',
    validation_status varchar(30) NOT NULL DEFAULT 'PENDING',
    current_version_flag boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_number),
    UNIQUE (document_id, sha256_checksum),
    CONSTRAINT kb_extraction_status_ck CHECK (
        extraction_status IN ('PENDING','RUNNING','COMPLETED','FAILED','SKIPPED')
    ),
    CONSTRAINT kb_validation_status_ck CHECK (
        validation_status IN ('PENDING','PASSED','WARNING','FAILED')
    )
);

CREATE UNIQUE INDEX kb_one_current_version_ux
ON kb.document_version(document_id)
WHERE current_version_flag;

CREATE TABLE kb.document_chunk (
    chunk_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL REFERENCES kb.document_version(document_version_id) ON DELETE CASCADE,
    chunk_sequence    integer NOT NULL,
    heading_path      text,
    chapter_title     text,
    section_title     text,
    section_anchor    text,
    page_number       integer,
    content_text      text NOT NULL,
    token_count       integer,
    content_hash      varchar(64) NOT NULL,
    search_vector     tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(heading_path, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(section_title, '')), 'A') ||
        setweight(to_tsvector('english', content_text), 'B')
    ) STORED,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, chunk_sequence),
    UNIQUE (document_version_id, content_hash)
);

CREATE TABLE kb.embedding_model (
    embedding_model_code varchar(100) PRIMARY KEY,
    provider_name     varchar(100) NOT NULL,
    model_name        varchar(200) NOT NULL,
    vector_dimension  integer NOT NULL,
    active_flag       boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- The starter package uses 1536-dimensional embeddings.
-- Add a separate table/index when adopting another vector dimension.
CREATE TABLE kb.chunk_embedding_1536 (
    chunk_id          uuid PRIMARY KEY REFERENCES kb.document_chunk(chunk_id) ON DELETE CASCADE,
    embedding_model_code varchar(100) NOT NULL REFERENCES kb.embedding_model(embedding_model_code),
    embedding         vector(1536) NOT NULL,
    embedded_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE kb.document_permission (
    document_id       uuid NOT NULL REFERENCES kb.document(document_id) ON DELETE CASCADE,
    principal_type    varchar(30) NOT NULL,
    principal_code    varchar(200) NOT NULL,
    permission_code   varchar(30) NOT NULL DEFAULT 'READ',
    PRIMARY KEY (document_id, principal_type, principal_code, permission_code),
    CONSTRAINT kb_permission_principal_ck CHECK (
        principal_type IN (
            'ROLE','SUPPORT_GROUP','BUSINESS_UNIT','DEPARTMENT',
            'USER','ALL_EMPLOYEES','ALL_ANALYSTS'
        )
    ),
    CONSTRAINT kb_permission_code_ck CHECK (
        permission_code IN ('READ','AUTHOR','APPROVE','ADMINISTER')
    )
);

CREATE TABLE kb.ingestion_manifest_entry (
    manifest_entry_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid REFERENCES identity.tenant(tenant_id),
    source_id         uuid NOT NULL REFERENCES kb.source(source_id),
    release_id        uuid REFERENCES kb.release(release_id),
    product_node_id   uuid REFERENCES kb.product_node(product_node_id),
    manifest_key      varchar(500) NOT NULL,
    document_title    text NOT NULL,
    document_type     varchar(60) NOT NULL,
    audience_code     varchar(30) NOT NULL,
    canonical_url     text,
    pdf_url           text,
    html_url          text,
    local_file_path   text,
    target_collection varchar(120) NOT NULL,
    security_classification varchar(30) NOT NULL DEFAULT 'INTERNAL',
    acquisition_permission varchar(30) NOT NULL DEFAULT 'PENDING',
    permission_reference text,
    acquisition_method varchar(40) NOT NULL,
    enabled_flag      boolean NOT NULL DEFAULT true,
    expected_sha256   varchar(64),
    notes             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, manifest_key),
    CONSTRAINT manifest_permission_ck CHECK (
        acquisition_permission IN ('PENDING','APPROVED','REJECTED','NOT_REQUIRED')
    ),
    CONSTRAINT manifest_method_ck CHECK (
        acquisition_method IN (
            'MANUAL_UPLOAD','APPROVED_DIRECT_DOWNLOAD','API_FEED',
            'REPOSITORY_CONNECTOR','TICKET_PUBLICATION'
        )
    )
);

CREATE TRIGGER manifest_entry_set_updated_at
BEFORE UPDATE ON kb.ingestion_manifest_entry
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

CREATE TABLE kb.ingestion_run (
    ingestion_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid REFERENCES identity.tenant(tenant_id),
    run_type          varchar(30) NOT NULL,
    run_status        varchar(30) NOT NULL DEFAULT 'QUEUED',
    started_at        timestamptz,
    completed_at      timestamptz,
    requested_by      uuid REFERENCES identity.app_user(user_id),
    worker_name       varchar(200),
    configuration_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    total_items       integer NOT NULL DEFAULT 0,
    completed_items   integer NOT NULL DEFAULT 0,
    failed_items      integer NOT NULL DEFAULT 0,
    error_summary     text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ingestion_run_type_ck CHECK (
        run_type IN ('ACQUISITION','EXTRACTION','CHUNKING','EMBEDDING','VALIDATION','FULL_PIPELINE')
    ),
    CONSTRAINT ingestion_run_status_ck CHECK (
        run_status IN ('QUEUED','RUNNING','COMPLETED','COMPLETED_WITH_ERRORS','FAILED','CANCELLED')
    )
);

CREATE TABLE kb.ingestion_run_item (
    ingestion_run_item_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ingestion_run_id uuid NOT NULL REFERENCES kb.ingestion_run(ingestion_run_id) ON DELETE CASCADE,
    manifest_entry_id uuid NOT NULL REFERENCES kb.ingestion_manifest_entry(manifest_entry_id),
    item_status       varchar(30) NOT NULL DEFAULT 'QUEUED',
    document_id       uuid REFERENCES kb.document(document_id),
    document_version_id uuid REFERENCES kb.document_version(document_version_id),
    attempt_count     integer NOT NULL DEFAULT 0,
    started_at        timestamptz,
    completed_at      timestamptz,
    downloaded_uri    text,
    observed_sha256   varchar(64),
    page_count        integer,
    chunk_count       integer,
    warning_json      jsonb NOT NULL DEFAULT '[]'::jsonb,
    error_code        varchar(100),
    error_message     text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ingestion_run_id, manifest_entry_id),
    CONSTRAINT ingestion_item_status_ck CHECK (
        item_status IN (
            'QUEUED','ACQUIRING','ACQUIRED','EXTRACTING','EXTRACTED',
            'CHUNKING','CHUNKED','EMBEDDING','EMBEDDED','VALIDATING',
            'PUBLISHED','SKIPPED_UNCHANGED','BLOCKED_PERMISSION','FAILED'
        )
    )
);

CREATE TRIGGER ingestion_run_item_set_updated_at
BEFORE UPDATE ON kb.ingestion_run_item
FOR EACH ROW EXECUTE FUNCTION util.set_updated_at();

ALTER TABLE kb.document_version
ADD CONSTRAINT kb_document_version_ingestion_run_fk
FOREIGN KEY (acquisition_run_id) REFERENCES kb.ingestion_run(ingestion_run_id);

CREATE INDEX kb_document_chunk_fts_ix
ON kb.document_chunk USING gin (search_vector);

CREATE INDEX kb_document_chunk_heading_trgm_ix
ON kb.document_chunk USING gin (heading_path gin_trgm_ops);

CREATE INDEX kb_chunk_embedding_1536_hnsw_ix
ON kb.chunk_embedding_1536
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX kb_document_lookup_ix
ON kb.document (release_id, product_node_id, document_type, approval_status, active_flag);

CREATE INDEX kb_ingestion_manifest_status_ix
ON kb.ingestion_manifest_entry (acquisition_permission, enabled_flag, source_id);

COMMIT;
