"""Publish the governed default hybrid retrieval fusion configuration."""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_retrieval_fusion"
down_revision: str | None = "0015_hybrid_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO ai.retrieval_configuration(
          retrieval_configuration_id,tenant_id,retrieval_code,retrieval_name,active_flag)
        VALUES ('71000000-0000-0000-0000-000000000001',NULL,'HYBRID_EVIDENCE',
          'Hybrid evidence retrieval',true)
        ON CONFLICT (retrieval_configuration_id) DO NOTHING;

        INSERT INTO ai.retrieval_configuration_version(
          retrieval_configuration_version_id,retrieval_configuration_id,version_number,
          version_status,configuration_json,effective_from,approved_at,change_reason,published_at)
        VALUES (
          '71000000-0000-0000-0000-000000000002',
          '71000000-0000-0000-0000-000000000001',1,'PUBLISHED',
          '{
            "rrf_k": 60,
            "lexical_weight": 1.0,
            "vector_weight": 1.0,
            "exact_identifier_boost": 0.35,
            "metadata_boost": 0.08,
            "rerank_weight": 0.25,
            "reranking_enabled": false,
            "source_authority_weights": {
              "COMPANY_POLICY": 0.10,
              "COMPANY_PROCEDURE": 0.08,
              "ORACLE_PUBLIC_DOCUMENTATION": 0.06,
              "INTERNAL_KNOWLEDGE": 0.04,
              "HISTORICAL_RESOLUTION": 0.02
            }
          }'::jsonb,now(),now(),
          'System bootstrap configuration for Milestone 7 evidence retrieval',now())
        ON CONFLICT (retrieval_configuration_version_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    # Published configuration versions are intentionally immutable. Retaining the bootstrap
    # version makes downgrade/re-upgrade safe without disabling the governance trigger.
    pass
