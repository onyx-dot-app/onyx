"""update_kg_trigger_functions

Revision ID: 36e9220ab794
Revises: c9e2cd766c29
Create Date: 2025-06-22 17:33:25.833733

"""

from alembic import op
from sqlalchemy.orm import Session
from sqlalchemy import text
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

# revision identifiers, used by Alembic.
revision = "36e9220ab794"
down_revision = "c9e2cd766c29"
branch_labels = None
depends_on = None


def _get_tenant_contextvar(session: Session) -> str:
    """Get the current schema for the migration"""
    current_tenant = session.execute(text("SELECT current_schema()")).scalar()
    if isinstance(current_tenant, str):
        return current_tenant
    else:
        raise ValueError("Current tenant is not a string")


def upgrade() -> None:

    bind = op.get_bind()
    session = Session(bind=bind)

    # Create kg_entity trigger to update kg_entity.name and its trigrams
    tenant_id = _get_tenant_contextvar(session)
    alphanum_pattern = r"[^a-z0-9]+"
    truncate_length = 1000
    function = "update_kg_entity_name"
    op.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION "{tenant_id}".{function}()
            RETURNS TRIGGER AS $$
            DECLARE
                name text;
                cleaned_name text;
            BEGIN
                -- Set name to semantic_id if document_id is not NULL
                IF NEW.document_id IS NOT NULL THEN
                    SELECT lower(semantic_id) INTO name
                    FROM "{tenant_id}".document
                    WHERE id = NEW.document_id;
                ELSE
                    name = lower(NEW.name);
                END IF;

                -- Clean name and truncate if too long
                cleaned_name = regexp_replace(
                    name,
                    '{alphanum_pattern}', '', 'g'
                );
                IF length(cleaned_name) > {truncate_length} THEN
                    cleaned_name = left(cleaned_name, {truncate_length});
                END IF;

                -- Set name and name trigrams
                NEW.name = name;
                NEW.name_trigrams = {POSTGRES_DEFAULT_SCHEMA}.show_trgm(cleaned_name);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    trigger = f"{function}_trigger"
    op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON "{tenant_id}".kg_entity')
    op.execute(
        f"""
        CREATE TRIGGER {trigger}
            BEFORE INSERT OR UPDATE OF name
            ON "{tenant_id}".kg_entity
            FOR EACH ROW
            EXECUTE FUNCTION "{tenant_id}".{function}();
        """
    )

    # Create kg_entity trigger to update kg_entity.name and its trigrams
    function = "update_kg_entity_name_from_doc"
    op.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION "{tenant_id}".{function}()
            RETURNS TRIGGER AS $$
            DECLARE
                doc_name text;
                cleaned_name text;
            BEGIN
                doc_name = lower(NEW.semantic_id);

                -- Clean name and truncate if too long
                cleaned_name = regexp_replace(
                    doc_name,
                    '{alphanum_pattern}', '', 'g'
                );
                IF length(cleaned_name) > {truncate_length} THEN
                    cleaned_name = left(cleaned_name, {truncate_length});
                END IF;

                -- Set name and name trigrams for all entities referencing this document
                UPDATE "{tenant_id}".kg_entity
                SET
                    name = doc_name,
                    name_trigrams = {POSTGRES_DEFAULT_SCHEMA}.show_trgm(cleaned_name)
                WHERE document_id = NEW.id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    trigger = f"{function}_trigger"
    op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON "{tenant_id}".document')
    op.execute(
        f"""
        CREATE TRIGGER {trigger}
            AFTER UPDATE OF semantic_id
            ON "{tenant_id}".document
            FOR EACH ROW
            EXECUTE FUNCTION "{tenant_id}".{function}();
        """
    )


def downgrade() -> None:
    pass
