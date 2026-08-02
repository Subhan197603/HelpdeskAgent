"""Add authorization and metadata indexes for bounded hybrid retrieval."""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_hybrid_retrieval"
down_revision: str | None = "0014_knowledge_processing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX document_permission_retrieval_ix
          ON kb.document_permission(document_id,permission_code,principal_type,principal_code);
        CREATE INDEX document_retrieval_filters_ix
          ON kb.document(tenant_id,active_flag,approval_status,language_code,
            source_id,release_id,product_node_id);
        CREATE INDEX product_node_retrieval_lineage_ix
          ON kb.product_node(parent_product_node_id,product_level,product_code);
        CREATE INDEX source_retrieval_active_ix
          ON kb.source(source_id,tenant_id) WHERE active_flag;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX kb.source_retrieval_active_ix;
        DROP INDEX kb.product_node_retrieval_lineage_ix;
        DROP INDEX kb.document_retrieval_filters_ix;
        DROP INDEX kb.document_permission_retrieval_ix;
        """
    )
