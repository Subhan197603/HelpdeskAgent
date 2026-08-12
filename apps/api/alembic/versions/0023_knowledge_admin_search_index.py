"""Add the bounded title-search index for knowledge administration.

Task 11.5D adds tenant-scoped administrative browsing over existing knowledge
documents. It does not add document, version, permission, or delete grants.
The trigram index supports the approved literal substring title search without
changing public reader or retrieval eligibility.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023_knowledge_admin_index"
down_revision: str | None = "0022_admin_config_privileges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "document_admin_title_trgm_ix",
        "document",
        ["document_title"],
        schema="kb",
        postgresql_using="gin",
        postgresql_ops={"document_title": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("document_admin_title_trgm_ix", table_name="document", schema="kb")
