"""kg normalization

Revision ID: 37c333d8e6e8
Revises: 495cb26ce93e
Create Date: 2025-05-20 15:02:00.840944

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from onyx.db.models import NullFilteredString


# revision identifiers, used by Alembic.
revision = "37c333d8e6e8"
down_revision = "495cb26ce93e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pg_trgm extension if not already enabled
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Add semantic_id and trigrams columns
    op.add_column(
        "kg_entity",
        sa.Column("semantic_id", NullFilteredString, nullable=True),
    )
    op.add_column(
        "kg_entity",
        sa.Column(
            "semantic_id_trigrams", postgresql.ARRAY(sa.String(3)), nullable=True
        ),
    )

    # Create GIN index on semantic_id_trigrams
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_entity_semantic_id_trigrams "
        "ON kg_entity USING GIN (semantic_id_trigrams)"
    )

    # Define regex patterns in Python
    alphanum_pattern = r"[^a-z0-9]+"
    email_pattern = r"(?<=\S)@([a-z0-9-]+)\.([a-z]{2,6})$"

    # Create trigger to update semantic_id and trigrams if document_id or semantic_id changes
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION update_kg_entity_semantic_id()
        RETURNS TRIGGER AS $$
        DECLARE
            doc_semantic_id text;
        BEGIN
            -- Get semantic_id from document if document_id exists
            IF NEW.document_id IS NOT NULL THEN
                SELECT semantic_id INTO doc_semantic_id
                FROM document
                WHERE id = NEW.document_id;
            END IF;

            -- Set semantic_id and trigrams
            NEW.semantic_id = COALESCE(doc_semantic_id, '');
            NEW.semantic_id_trigrams = show_trgm(
                regexp_replace(
                    regexp_replace(
                        lower(NEW.semantic_id),
                        '{alphanum_pattern}', '', 'g'
                    ),
                    '{email_pattern}', '', 'g'
                )
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS kg_entity_semantic_id_trigger ON kg_entity")
    op.execute(
        """
        CREATE TRIGGER kg_entity_semantic_id_trigger
            BEFORE INSERT OR UPDATE OF document_id
            ON kg_entity
            FOR EACH ROW
            EXECUTE FUNCTION update_kg_entity_semantic_id();
        """
    )

    # Create trigger to update kg_entity semantic_id and trigrams when document.semantic_id changes
    # Can only manually override semantic_id if document_id is NULL, perhaps useful for ungrounded entities
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION update_kg_entity_semantic_id_from_doc()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Update semantic_id and trigrams for all entities referencing this document
            UPDATE kg_entity
            SET
                semantic_id = COALESCE(NEW.semantic_id, ''),
                semantic_id_trigrams = show_trgm(
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
    op.execute(
        "DROP TRIGGER IF EXISTS update_kg_entity_semantic_id_from_doc_trigger ON document"
    )
    op.execute(
        """
        CREATE TRIGGER update_kg_entity_semantic_id_from_doc_trigger
            AFTER UPDATE OF semantic_id
            ON document
            FOR EACH ROW
            EXECUTE FUNCTION update_kg_entity_semantic_id_from_doc();
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
    op.execute("DROP TRIGGER IF EXISTS kg_entity_semantic_id_trigger ON kg_entity")
    op.execute(
        "DROP TRIGGER IF EXISTS update_kg_entity_semantic_id_from_doc_trigger ON document"
    )

    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS update_kg_entity_semantic_id()")
    op.execute("DROP FUNCTION IF EXISTS update_kg_entity_semantic_id_from_doc()")

    # Drop index
    op.execute("COMMIT")  # Commit to allow CONCURRENTLY
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_kg_entity_semantic_id_trigrams")

    # Drop column
    op.drop_column("kg_entity", "semantic_id_trigrams")
    op.drop_column("kg_entity", "semantic_id")
