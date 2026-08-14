"""Add private analyst canned responses.

Canned responses are tenant- and owner-scoped plaintext preferences. They do
not post comments, select visibility, or grant access to tickets.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025_analyst_canned_responses"
down_revision: str | None = "0024_analyst_saved_filters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE config.analyst_canned_response (
          canned_response_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          owner_user_id uuid NOT NULL REFERENCES identity.app_user(user_id),
          response_name varchar(100) NOT NULL,
          response_body varchar(10000) NOT NULL,
          display_order integer NOT NULL DEFAULT 0,
          row_version integer NOT NULL DEFAULT 1,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT analyst_canned_response_name_ck CHECK (
            response_name = btrim(response_name, E' \t\n\r')
            AND length(response_name) BETWEEN 1 AND 100
          ),
          CONSTRAINT analyst_canned_response_body_ck CHECK (
            response_body = btrim(response_body, E' \t\n\r')
            AND length(response_body) BETWEEN 1 AND 10000
          ),
          CONSTRAINT analyst_canned_response_order_ck CHECK (display_order >= 0),
          CONSTRAINT analyst_canned_response_version_ck CHECK (row_version > 0)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX analyst_canned_response_owner_name_ux "
        "ON config.analyst_canned_response "
        "(tenant_id,owner_user_id,lower(response_name))"
    )
    op.execute(
        "CREATE INDEX analyst_canned_response_owner_order_ix "
        "ON config.analyst_canned_response "
        "(tenant_id,owner_user_id,display_order,canned_response_id)"
    )
    op.execute("ALTER TABLE config.analyst_canned_response ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY analyst_canned_response_owner_isolation
        ON config.analyst_canned_response
        USING (
          tenant_id=util.current_tenant_id()
          AND owner_user_id=util.current_user_id()
        )
        WITH CHECK (
          tenant_id=util.current_tenant_id()
          AND owner_user_id=util.current_user_id()
        )
        """
    )
    op.execute(
        "GRANT SELECT,INSERT,UPDATE,DELETE ON config.analyst_canned_response TO helpdesk_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT,INSERT,UPDATE,DELETE ON config.analyst_canned_response FROM helpdesk_app"
    )
    op.execute(
        "DROP POLICY analyst_canned_response_owner_isolation ON config.analyst_canned_response"
    )
    op.drop_table("analyst_canned_response", schema="config")
