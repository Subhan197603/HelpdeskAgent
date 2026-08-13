"""Add private analyst saved ticket filters.

Saved filters contain only the scalar inputs already accepted by the analyst
queue endpoint. They are tenant- and owner-scoped preference records and do
not own tickets or grant queue or ticket access.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_analyst_saved_filters"
down_revision: str | None = "0023_knowledge_admin_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE config.analyst_saved_filter (
          saved_filter_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES identity.tenant(tenant_id),
          owner_user_id uuid NOT NULL REFERENCES identity.app_user(user_id),
          filter_name varchar(100) NOT NULL,
          queue_id uuid NOT NULL REFERENCES config.queue_definition(queue_id),
          status_code varchar(50),
          priority_code varchar(20) REFERENCES config.priority(priority_code),
          search_text varchar(100),
          assignment_group_id uuid REFERENCES identity.support_group(support_group_id),
          assignee_scope varchar(20),
          display_order integer NOT NULL DEFAULT 0,
          row_version integer NOT NULL DEFAULT 1,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT analyst_saved_filter_name_ck CHECK (
            filter_name = btrim(filter_name) AND length(filter_name) BETWEEN 1 AND 100
          ),
          CONSTRAINT analyst_saved_filter_status_ck CHECK (
            status_code IS NULL OR status_code ~ '^[A-Z][A-Z0-9_]{0,49}$'
          ),
          CONSTRAINT analyst_saved_filter_priority_ck CHECK (
            priority_code IS NULL OR priority_code ~ '^[A-Z][A-Z0-9_]{0,19}$'
          ),
          CONSTRAINT analyst_saved_filter_search_ck CHECK (
            search_text IS NULL OR (
              search_text = btrim(search_text) AND length(search_text) BETWEEN 2 AND 100
            )
          ),
          CONSTRAINT analyst_saved_filter_assignee_ck CHECK (
            assignee_scope IS NULL OR assignee_scope IN ('me', 'unassigned')
          ),
          CONSTRAINT analyst_saved_filter_order_ck CHECK (display_order >= 0),
          CONSTRAINT analyst_saved_filter_version_ck CHECK (row_version > 0)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX analyst_saved_filter_owner_name_ux "
        "ON config.analyst_saved_filter (tenant_id,owner_user_id,lower(filter_name))"
    )
    op.execute(
        "CREATE INDEX analyst_saved_filter_owner_order_ix "
        "ON config.analyst_saved_filter "
        "(tenant_id,owner_user_id,display_order,saved_filter_id)"
    )
    op.execute("ALTER TABLE config.analyst_saved_filter ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY analyst_saved_filter_owner_isolation
        ON config.analyst_saved_filter
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
    op.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON config.analyst_saved_filter TO helpdesk_app")


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT,INSERT,UPDATE,DELETE ON config.analyst_saved_filter FROM helpdesk_app"
    )
    op.execute("DROP POLICY analyst_saved_filter_owner_isolation ON config.analyst_saved_filter")
    op.drop_table("analyst_saved_filter", schema="config")
