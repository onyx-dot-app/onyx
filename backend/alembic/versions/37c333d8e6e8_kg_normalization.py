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

    # Add clustering columns
    op.add_column(
        "kg_entity",
        sa.Column("clustering_name", NullFilteredString, nullable=True),
    )
    op.add_column(
        "kg_entity",
        sa.Column("clustering_trigrams", postgresql.ARRAY(sa.String(3)), nullable=True),
    )
    op.add_column(
        "kg_entity_extraction_staging",
        sa.Column("clustering_name", NullFilteredString, nullable=True),
    )
    op.add_column(
        "kg_entity_extraction_staging",
        sa.Column("clustered", sa.Boolean, nullable=False, server_default="false"),
    )

    # Create GIN index on clustering columns
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_entity_clustering_trigrams "
        "ON kg_entity USING GIN (clustering_trigrams)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_entity_extraction_clustering_trigrams "
        "ON kg_entity_extraction_staging USING GIN (clustering_name gin_trgm_ops)"
    )

    # Create trigger to update clustering columns if document_id changes
    alphanum_pattern = r"[^a-z0-9]+"
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION update_kg_entity_clustering()
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
                lower(COALESCE(doc_semantic_id, NEW.name)),
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
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_kg_entity_extraction_clustering()
        RETURNS TRIGGER AS $$
        DECLARE
            doc_semantic_id text;
        BEGIN
            -- Get semantic_id from document
            SELECT semantic_id INTO doc_semantic_id
            FROM document
            WHERE id = NEW.document_id;

            -- Set clustering_name to semantic_id
            NEW.clustering_name = lower(COALESCE(doc_semantic_id, NEW.name));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table, function in (
        ("kg_entity", "update_kg_entity_clustering"),
        ("kg_entity_extraction_staging", "update_kg_entity_extraction_clustering"),
    ):
        trigger = f"{function}_trigger"
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
                BEFORE INSERT OR UPDATE OF document_id
                ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION {function}();
            """
        )

    # Create trigger to update kg_entity clustering_name and its trigrams when document.clustering_name changes
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION update_kg_entity_clustering_from_doc()
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
        """
        CREATE OR REPLACE FUNCTION update_kg_entity_extraction_clustering_from_doc()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE kg_entity_extraction_staging
            SET
                clustering_name = lower(COALESCE(NEW.semantic_id, ''))
            WHERE document_id = NEW.id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for function in (
        "update_kg_entity_clustering_from_doc",
        "update_kg_entity_extraction_clustering_from_doc",
    ):
        trigger = f"{function}_trigger"
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON document")
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
                AFTER UPDATE OF semantic_id
                ON document
                FOR EACH ROW
                EXECUTE FUNCTION {function}();
            """
        )

    # Force update all existing rows by triggering the function
    op.execute(
        """
        UPDATE kg_entity
        SET document_id = document_id;
        """
    )
    op.execute(
        """
        UPDATE kg_entity_extraction_staging
        SET document_id = document_id;
        """
    )


def downgrade() -> None:
    # Drop triggers and functions
    for table, function in (
        ("kg_entity", "update_kg_entity_clustering"),
        ("kg_entity_extraction_staging", "update_kg_entity_extraction_clustering"),
        ("document", "update_kg_entity_clustering_from_doc"),
        ("document", "update_kg_entity_extraction_clustering_from_doc"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {function}_trigger ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")

    # Drop index
    op.execute("COMMIT")  # Commit to allow CONCURRENTLY
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_kg_entity_clustering_trigrams")
    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS idx_kg_entity_extraction_clustering_trigrams"
    )

    # Drop column
    op.drop_column("kg_entity", "clustering_trigrams")
    op.drop_column("kg_entity", "clustering_name")
    op.drop_column("kg_entity_extraction_staging", "clustering_name")
    op.drop_column("kg_entity_extraction_staging", "clustered")
