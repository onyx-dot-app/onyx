"""kg normalization

Revision ID: 37c333d8e6e8
Revises: 495cb26ce93e
Create Date: 2025-05-20 15:02:00.840944

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "37c333d8e6e8"
down_revision = "495cb26ce93e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pg_trgm extension if not already enabled
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Add trigrams column
    op.add_column(
        "kg_entity",
        sa.Column("trigrams", postgresql.ARRAY(sa.String(3)), nullable=True),
    )

    # Create GIN index on trigrams
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_entity_trigrams "
        "ON kg_entity USING GIN (trigrams)"
    )

    # Define regex patterns in Python
    alphanum_pattern = r"[^a-z0-9]+"
    email_pattern = r"(?<=\S)@([a-z0-9-]+)\.([a-z]{2,6})$"

    # Create trigger to populate trigrams if kg_entity.document_id changes
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION update_kg_entity_trigrams()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Get semantic_id from document and generate trigrams
            SELECT show_trgm(
                regexp_replace(
                    regexp_replace(
                        lower(COALESCE(semantic_id, '')),
                        '{alphanum_pattern}', '', 'g'
                    ),
                    '{email_pattern}', '', 'g'
                )
            ) INTO NEW.trigrams
            FROM document
            WHERE id = NEW.document_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Create new trigger
    op.execute("DROP TRIGGER IF EXISTS kg_entity_trigrams_trigger ON kg_entity")
    op.execute(
        """
        CREATE TRIGGER kg_entity_trigrams_trigger
            BEFORE INSERT OR UPDATE OF document_id
            ON kg_entity
            FOR EACH ROW
            EXECUTE FUNCTION update_kg_entity_trigrams();
        """
    )

    # Create trigger to populate kg_entity.trigrams if document.semantic_id changes
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION update_kg_entity_trigrams_from_doc()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Update trigrams for all entities referencing this document
            UPDATE kg_entity
            SET trigrams = show_trgm(
                regexp_replace(
                    regexp_replace(
                        lower(COALESCE(NEW.semantic_id, '')),
                        '{alphanum_pattern}', '', 'g'
                    ),
                    '{email_pattern}', '', 'g'
                )
            )
            WHERE document_id = NEW.id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Create new trigger
    op.execute(
        "DROP TRIGGER IF EXISTS update_kg_entity_trigrams_from_doc_trigger ON document"
    )
    op.execute(
        """
        CREATE TRIGGER update_kg_entity_trigrams_from_doc_trigger
            AFTER UPDATE OF semantic_id
            ON document
            FOR EACH ROW
            EXECUTE FUNCTION update_kg_entity_trigrams_from_doc();
        """
    )

    # Force update all existing rows by triggering the function
    op.execute(
        """
        UPDATE kg_entity
        SET document_id = document_id;
        """
    )


def downgrade() -> None:
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS kg_entity_trigrams_trigger ON kg_entity")
    op.execute(
        "DROP TRIGGER IF EXISTS update_kg_entity_trigrams_from_doc_trigger ON document"
    )

    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS update_kg_entity_trigrams()")
    op.execute("DROP FUNCTION IF EXISTS update_kg_entity_trigrams_from_doc()")

    # Drop index
    op.execute("COMMIT")  # Commit to allow CONCURRENTLY
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_kg_entity_trigrams")

    # Drop column
    op.drop_column("kg_entity", "trigrams")
