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

    # Add clustering_name and trigrams columns
    op.add_column(
        "kg_entity",
        sa.Column("clustering_name", NullFilteredString, nullable=True),
    )
    op.add_column(
        "kg_entity",
        sa.Column("clustering_trigrams", postgresql.ARRAY(sa.String(3)), nullable=True),
    )

    # Create GIN index on clustering_trigrams
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_entity_clustering_trigrams "
        "ON kg_entity USING GIN (clustering_trigrams)"
    )

    # Define regex patterns in Python
    alphanum_pattern = r"[^a-z0-9]+"

    # Create trigger to update clustering_name and its trigrams if document_id changes
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION update_kg_entity_clustering_data()
        RETURNS TRIGGER AS $$
        DECLARE
            doc_semantic_id text;
            cleaned_semantic_id text;
        BEGIN
            -- Get semantic_id from document
            SELECT semantic_id INTO doc_semantic_id
            FROM document
            WHERE id = NEW.document_id;

            -- Clean the semantic_id with regex patterns
            cleaned_semantic_id = regexp_replace(
                lower(COALESCE(doc_semantic_id, NEW.id_name)),
                '{alphanum_pattern}', '', 'g'
            );

            -- Set clustering_name to cleaned version and generate trigrams
            NEW.clustering_name = cleaned_semantic_id;
            NEW.clustering_trigrams = show_trgm(cleaned_semantic_id);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS kg_entity_clustering_data_trigger ON kg_entity")
    op.execute(
        """
        CREATE TRIGGER kg_entity_clustering_data_trigger
            BEFORE INSERT OR UPDATE OF document_id
            ON kg_entity
            FOR EACH ROW
            EXECUTE FUNCTION update_kg_entity_clustering_data();
        """
    )

    # Create trigger to update kg_entity clustering_name and its trigrams when document.clustering_name changes
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION update_kg_entity_clustering_data_from_doc()
        RETURNS TRIGGER AS $$
        DECLARE
            cleaned_semantic_id text;
        BEGIN
            -- Clean the semantic_id with regex patterns
            cleaned_semantic_id = regexp_replace(
                lower(COALESCE(NEW.semantic_id, '')),
                '{alphanum_pattern}', '', 'g'
            );

            -- Update clustering name and trigrams for all entities referencing this document
            UPDATE kg_entity
            SET
                clustering_name = cleaned_semantic_id,
                clustering_trigrams = show_trgm(cleaned_semantic_id)
            WHERE document_id = NEW.id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS update_kg_entity_clustering_data_from_doc_trigger ON document"
    )
    op.execute(
        """
        CREATE TRIGGER update_kg_entity_clustering_data_from_doc_trigger
            AFTER UPDATE OF semantic_id
            ON document
            FOR EACH ROW
            EXECUTE FUNCTION update_kg_entity_clustering_data_from_doc();
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
    op.execute("DROP TRIGGER IF EXISTS kg_entity_clustering_data_trigger ON kg_entity")
    op.execute(
        "DROP TRIGGER IF EXISTS update_kg_entity_clustering_data_from_doc_trigger ON document"
    )

    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS update_kg_entity_clustering_data()")
    op.execute("DROP FUNCTION IF EXISTS update_kg_entity_clustering_data_from_doc()")

    # Drop index
    op.execute("COMMIT")  # Commit to allow CONCURRENTLY
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_kg_entity_clustering_trigrams")

    # Drop column
    op.drop_column("kg_entity", "clustering_trigrams")
    op.drop_column("kg_entity", "clustering_name")
