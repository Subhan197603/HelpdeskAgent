"""Protect all components referenced by a published request form."""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_catalogue_form_immutability"
down_revision: str | None = "0004_oidc_external_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION config.protect_published_request_type_field()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM config.request_type_version AS version
                WHERE version.version_status = 'PUBLISHED'
                  AND version.request_type_version_id IN (
                      CASE WHEN TG_OP = 'INSERT' THEN NEW.request_type_version_id
                           ELSE OLD.request_type_version_id END,
                      CASE WHEN TG_OP = 'DELETE' THEN OLD.request_type_version_id
                           ELSE NEW.request_type_version_id END
                  )
            ) THEN
                RAISE EXCEPTION 'Published request-form configuration is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION config.protect_published_custom_field()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM config.request_type_field AS layout
                JOIN config.request_type_version AS version
                  ON version.request_type_version_id = layout.request_type_version_id
                WHERE layout.custom_field_id IN (
                    CASE WHEN TG_OP = 'INSERT' THEN NEW.custom_field_id
                         ELSE OLD.custom_field_id END,
                    CASE WHEN TG_OP = 'DELETE' THEN OLD.custom_field_id
                         ELSE NEW.custom_field_id END
                )
                  AND version.version_status = 'PUBLISHED'
            ) THEN
                RAISE EXCEPTION 'Published request-form configuration is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION config.protect_published_custom_field_option()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM config.request_type_field AS layout
                JOIN config.request_type_version AS version
                  ON version.request_type_version_id = layout.request_type_version_id
                WHERE layout.custom_field_id IN (
                    CASE WHEN TG_OP = 'INSERT' THEN NEW.custom_field_id
                         ELSE OLD.custom_field_id END,
                    CASE WHEN TG_OP = 'DELETE' THEN OLD.custom_field_id
                         ELSE NEW.custom_field_id END
                )
                  AND version.version_status = 'PUBLISHED'
            ) THEN
                RAISE EXCEPTION 'Published request-form configuration is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER request_type_field_protect_published
        BEFORE INSERT OR UPDATE OR DELETE ON config.request_type_field
        FOR EACH ROW EXECUTE FUNCTION config.protect_published_request_type_field();

        CREATE TRIGGER custom_field_protect_published
        BEFORE UPDATE OR DELETE ON config.custom_field
        FOR EACH ROW EXECUTE FUNCTION config.protect_published_custom_field();

        CREATE TRIGGER custom_field_option_protect_published
        BEFORE INSERT OR UPDATE OR DELETE ON config.custom_field_option
        FOR EACH ROW EXECUTE FUNCTION config.protect_published_custom_field_option();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER custom_field_option_protect_published
            ON config.custom_field_option;
        DROP TRIGGER custom_field_protect_published ON config.custom_field;
        DROP TRIGGER request_type_field_protect_published
            ON config.request_type_field;
        DROP FUNCTION config.protect_published_custom_field_option();
        DROP FUNCTION config.protect_published_custom_field();
        DROP FUNCTION config.protect_published_request_type_field();
        """
    )
