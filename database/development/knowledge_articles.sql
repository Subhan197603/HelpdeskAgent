\set ON_ERROR_STOP on

-- Optional deterministic local knowledge corpus. Never run this file in
-- production. Publishes four articles for the development tenant: three for
-- employees and one confidential analyst runbook.
BEGIN;

INSERT INTO kb.embedding_model (
    embedding_model_code, provider_name, model_name, vector_dimension
) VALUES ('DEFAULT_1536', 'local', 'deterministic', 1536)
ON CONFLICT (embedding_model_code) DO NOTHING;

INSERT INTO kb.source (
    source_id, tenant_id, source_code, source_name, source_type,
    acquisition_method, canonical_location, audience_scope, source_status,
    approval_status, approved_by, approved_at, owner_user_id,
    created_at, updated_at
) VALUES (
    'a0000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'DEV_HANDBOOK', 'IT Handbook', 'INTERNAL_KNOWLEDGE',
    'MANUAL_UPLOAD', 'https://kb.example.invalid', 'EMPLOYEE', 'ACTIVE',
    'APPROVED', '22000000-0000-0000-0000-000000000007',
    '2026-07-01T09:00:00Z', '22000000-0000-0000-0000-000000000007',
    '2026-07-01T09:00:00Z', '2026-07-01T09:00:00Z'
) ON CONFLICT (source_id) DO NOTHING;

CREATE OR REPLACE FUNCTION pg_temp.publish_seed_article(
    p_document uuid, p_version uuid, p_processing uuid,
    p_title text, p_type text, p_audience text, p_security text,
    p_stamp timestamptz,
    p_sections text[], p_bodies text[]
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    i integer;
BEGIN
    INSERT INTO kb.document (
        document_id, tenant_id, source_id, document_title, document_type,
        audience_code, language_code, security_classification,
        approval_status, approved_by, approved_at, canonical_url,
        created_at, updated_at
    ) VALUES (
        p_document, '20000000-0000-0000-0000-000000000001',
        'a0000000-0000-0000-0000-000000000001', p_title, p_type,
        p_audience, 'en', p_security,
        'APPROVED', '22000000-0000-0000-0000-000000000007', p_stamp,
        'https://kb.example.invalid/' || p_document,
        p_stamp, p_stamp
    ) ON CONFLICT (document_id) DO NOTHING;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO kb.document_version (
        document_version_id, document_id, version_number, original_file_uri,
        content_type, sha256_checksum, acquired_at, extraction_status,
        validation_status, current_version_flag
    ) VALUES (
        p_version, p_document, 1, 'file:///seed', 'text/markdown',
        repeat('b', 64), p_stamp, 'COMPLETED', 'PASSED', false
    );

    INSERT INTO kb.document_processing_version (
        processing_version_id, tenant_id, document_id, document_version_id,
        processing_number, parser_name, parser_version, chunker_name,
        chunker_version, chunking_configuration_json,
        chunking_configuration_hash, embedding_model_code, processing_status,
        validation_status, chunk_count, embedded_chunk_count,
        started_at, completed_at
    ) VALUES (
        p_processing, '20000000-0000-0000-0000-000000000001', p_document,
        p_version, 1, 'seed-parser', '1', 'seed-chunker', '1', '{}',
        repeat('c', 64), 'DEFAULT_1536', 'COMPLETED', 'PASSED',
        array_length(p_sections, 1), 0, p_stamp, p_stamp
    );

    UPDATE kb.document_version
    SET current_version_flag = true,
        published_processing_version_id = p_processing,
        published_at = p_stamp
    WHERE document_version_id = p_version;

    FOR i IN 1 .. array_length(p_sections, 1) LOOP
        INSERT INTO kb.document_chunk (
            chunk_id, document_version_id, chunk_sequence, heading_path,
            section_title, section_anchor, page_number, content_text,
            content_hash, processing_version_id, tenant_id, document_id,
            source_id, audience_code, security_classification,
            embedding_input_hash
        ) VALUES (
            gen_random_uuid(), p_version, i, p_sections[i],
            p_sections[i], 'section-' || i, i, p_bodies[i],
            lpad(to_hex(i), 64, '0'), p_processing,
            '20000000-0000-0000-0000-000000000001', p_document,
            'a0000000-0000-0000-0000-000000000001', p_audience, p_security,
            lpad(to_hex(i), 64, '0')
        );
    END LOOP;
END;
$$;

SELECT pg_temp.publish_seed_article(
    'a1000000-0000-0000-0000-000000000001',
    'a2000000-0000-0000-0000-000000000001',
    'a3000000-0000-0000-0000-000000000001',
    'Oracle Fusion login issues', 'FAQ', 'EMPLOYEE', 'INTERNAL',
    '2026-07-22T09:00:00Z',
    ARRAY['Overview', 'Resolution'],
    ARRAY[
        'Users may see authentication errors when signing in to Oracle Fusion. Password expiry is the most common cause.',
        'Reset the password from the self-service portal, then clear the browser cache before retrying.'
    ]
);

SELECT pg_temp.publish_seed_article(
    'a1000000-0000-0000-0000-000000000002',
    'a2000000-0000-0000-0000-000000000002',
    'a3000000-0000-0000-0000-000000000002',
    'Password reset guide', 'USER_GUIDE', 'EMPLOYEE', 'INTERNAL',
    '2026-07-21T09:00:00Z',
    ARRAY['Steps'],
    ARRAY[
        'Open the password portal, verify your identity, and choose a new password that meets the policy.'
    ]
);

SELECT pg_temp.publish_seed_article(
    'a1000000-0000-0000-0000-000000000003',
    'a2000000-0000-0000-0000-000000000003',
    'a3000000-0000-0000-0000-000000000003',
    'Report generation troubleshooting', 'PROCEDURE', 'EMPLOYEE', 'INTERNAL',
    '2026-07-20T09:00:00Z',
    ARRAY['Checks'],
    ARRAY[
        'When reports fail to generate, confirm the scheduler status and rerun the extract.'
    ]
);

SELECT pg_temp.publish_seed_article(
    'a1000000-0000-0000-0000-000000000004',
    'a2000000-0000-0000-0000-000000000004',
    'a3000000-0000-0000-0000-000000000004',
    'Invoice validation runbook', 'RUNBOOK', 'ANALYST', 'CONFIDENTIAL',
    '2026-07-23T09:00:00Z',
    ARRAY['Diagnosis'],
    ARRAY[
        'Check the invoice validation service queue depth and restart stuck workers.'
    ]
);

COMMIT;
