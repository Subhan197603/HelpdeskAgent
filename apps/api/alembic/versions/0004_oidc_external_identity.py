"""Add trusted OIDC tenant mappings and durable external identities."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_oidc_external_identity"
down_revision: str | None = "0003_rls_runtime_privileges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "app_user_tenant_user_uq",
        "app_user",
        ["tenant_id", "user_id"],
        schema="identity",
    )
    op.create_table(
        "oidc_tenant_mapping",
        sa.Column(
            "oidc_tenant_mapping_id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("identity.tenant.tenant_id"),
            nullable=False,
        ),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("trusted_issuer", sa.String(500), nullable=False),
        sa.Column("organization_claim_value", sa.String(300)),
        sa.Column("active_flag", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "oidc_tenant_mapping_id",
            name="oidc_tenant_mapping_tenant_id_uq",
        ),
        schema="identity",
    )
    op.execute(
        "CREATE UNIQUE INDEX oidc_tenant_mapping_trust_uq "
        "ON identity.oidc_tenant_mapping "
        "(provider_code, trusted_issuer, organization_claim_value) NULLS NOT DISTINCT"
    )
    op.create_index(
        "oidc_tenant_mapping_tenant_ix",
        "oidc_tenant_mapping",
        ["tenant_id", "active_flag"],
        schema="identity",
    )
    op.create_table(
        "external_identity",
        sa.Column(
            "external_identity_id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("oidc_tenant_mapping_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("external_subject", sa.String(300), nullable=False),
        sa.Column("active_flag", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "safe_provider_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True)),
        sa.Column("last_synchronized_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "oidc_tenant_mapping_id"],
            [
                "identity.oidc_tenant_mapping.tenant_id",
                "identity.oidc_tenant_mapping.oidc_tenant_mapping_id",
            ],
            name="external_identity_mapping_fk",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["identity.app_user.tenant_id", "identity.app_user.user_id"],
            name="external_identity_user_fk",
        ),
        sa.UniqueConstraint(
            "oidc_tenant_mapping_id",
            "external_subject",
            name="external_identity_mapping_subject_uq",
        ),
        sa.UniqueConstraint(
            "oidc_tenant_mapping_id",
            "user_id",
            name="external_identity_mapping_user_uq",
        ),
        schema="identity",
    )
    op.create_index(
        "external_identity_tenant_user_ix",
        "external_identity",
        ["tenant_id", "user_id", "active_flag"],
        schema="identity",
    )
    op.execute(
        "GRANT SELECT ON identity.oidc_tenant_mapping, identity.external_identity "
        "TO helpdesk_app, helpdesk_worker, helpdesk_reporting, helpdesk_readonly"
    )
    op.execute("GRANT INSERT ON identity.external_identity TO helpdesk_app")
    op.execute(
        "GRANT UPDATE (last_authenticated_at, last_synchronized_at, "
        "safe_provider_metadata_json) ON identity.external_identity TO helpdesk_app"
    )
    op.execute(
        "GRANT INSERT (tenant_id, external_subject, email_address, display_name, locale_code) "
        "ON identity.app_user TO helpdesk_app"
    )
    op.execute(
        "GRANT UPDATE (email_address, display_name, locale_code) "
        "ON identity.app_user TO helpdesk_app"
    )


def downgrade() -> None:
    op.drop_index(
        "external_identity_tenant_user_ix", table_name="external_identity", schema="identity"
    )
    op.drop_table("external_identity", schema="identity")
    op.drop_index(
        "oidc_tenant_mapping_tenant_ix", table_name="oidc_tenant_mapping", schema="identity"
    )
    op.drop_index(
        "oidc_tenant_mapping_trust_uq", table_name="oidc_tenant_mapping", schema="identity"
    )
    op.drop_table("oidc_tenant_mapping", schema="identity")
    op.drop_constraint("app_user_tenant_user_uq", "app_user", schema="identity", type_="unique")
