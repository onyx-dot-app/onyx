"""create knowledge graph tables

Revision ID: 495cb26ce93e
Revises: 238b84885828
Create Date: 2025-03-19 08:51:14.341989

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text
from datetime import datetime, timedelta

from onyx.configs.app_configs import DB_READONLY_USER
from onyx.configs.app_configs import DB_READONLY_PASSWORD
from shared_configs.configs import MULTI_TENANT
from onyx.db.models import NullFilteredString


# revision identifiers, used by Alembic.
revision = "495cb26ce93e"
down_revision = "238b84885828"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # Enable pg_trgm extension if not already enabled
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Create a new permission-less user to be later used for knowledge graph queries.
    # The user will later get temporary read priviledges for a specific view that will be
    # ad hoc generated specific to a knowledge graph query.
    #
    # Note: in order for the migration to run, the DB_READONLY_USER and DB_READONLY_PASSWORD
    # environment variables MUST be set. Otherwise, an exception will be raised.

    if not MULTI_TENANT:
        # Create read-only db user here only in single tenant mode. For multi-tenant mode,
        # the user is created in the alembic_tenants migration.
        if not (DB_READONLY_USER and DB_READONLY_PASSWORD):
            raise Exception("DB_READONLY_USER or DB_READONLY_PASSWORD is not set")

        op.execute(
            text(
                f"""
                DO $$
                BEGIN
                    -- Check if the read-only user already exists
                    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{DB_READONLY_USER}') THEN
                        -- Create the read-only user with the specified password
                        EXECUTE format('CREATE USER %I WITH PASSWORD %L', '{DB_READONLY_USER}', '{DB_READONLY_PASSWORD}');
                        -- First revoke all privileges to ensure a clean slate
                        EXECUTE format('REVOKE ALL ON DATABASE %I FROM %I', current_database(), '{DB_READONLY_USER}');
                        -- Grant only the CONNECT privilege to allow the user to connect to the database
                        -- but not perform any operations without additional specific grants
                        EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), '{DB_READONLY_USER}');
                    END IF;
                END
                $$;
                """
            )
        )

    op.create_table(
        "kg_config",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False, index=True),
        sa.Column("kg_variable_name", sa.String(), nullable=False, index=True),
        sa.Column("kg_variable_values", postgresql.ARRAY(sa.String()), nullable=False),
        sa.UniqueConstraint("kg_variable_name", name="uq_kg_config_variable_name"),
    )

    # Insert initial data into kg_config table
    op.bulk_insert(
        sa.table(
            "kg_config",
            sa.column("kg_variable_name", sa.String),
            sa.column("kg_variable_values", postgresql.ARRAY(sa.String)),
        ),
        [
            {"kg_variable_name": "KG_ENABLED", "kg_variable_values": ["false"]},
            {"kg_variable_name": "KG_VENDOR", "kg_variable_values": []},
            {"kg_variable_name": "KG_VENDOR_DOMAINS", "kg_variable_values": []},
            {"kg_variable_name": "KG_IGNORE_EMAIL_DOMAINS", "kg_variable_values": []},
            {
                "kg_variable_name": "KG_EXTRACTION_IN_PROGRESS",
                "kg_variable_values": ["false"],
            },
            {
                "kg_variable_name": "KG_CLUSTERING_IN_PROGRESS",
                "kg_variable_values": ["false"],
            },
            {
                "kg_variable_name": "KG_COVERAGE_START",
                "kg_variable_values": [
                    (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
                ],
            },
            {"kg_variable_name": "KG_MAX_COVERAGE_DAYS", "kg_variable_values": ["90"]},
        ],
    )

    op.create_table(
        "kg_entity_type",
        sa.Column("id_name", sa.String(), primary_key=True, nullable=False, index=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("grounding", sa.String(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
        sa.Column("occurrences", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, default=False),
        sa.Column("deep_extraction", sa.Boolean(), nullable=False, default=False),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("grounded_source_name", sa.String(), nullable=True),
        sa.Column("entity_values", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column(
            "clustering",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
    )

    # Create KGRelationshipType table
    op.create_table(
        "kg_relationship_type",
        sa.Column("id_name", sa.String(), primary_key=True, nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column(
            "source_entity_type_id_name", sa.String(), nullable=False, index=True
        ),
        sa.Column(
            "target_entity_type_id_name", sa.String(), nullable=False, index=True
        ),
        sa.Column("definition", sa.Boolean(), nullable=False, default=False),
        sa.Column("occurrences", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(), nullable=False, index=True),
        sa.Column("active", sa.Boolean(), nullable=False, default=True),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "clustering",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
        sa.ForeignKeyConstraint(
            ["source_entity_type_id_name"], ["kg_entity_type.id_name"]
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_type_id_name"], ["kg_entity_type.id_name"]
        ),
    )

    # Create KGRelationshipTypeExtractionStaging table
    op.create_table(
        "kg_relationship_type_extraction_staging",
        sa.Column("id_name", sa.String(), primary_key=True, nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column(
            "source_entity_type_id_name", sa.String(), nullable=False, index=True
        ),
        sa.Column(
            "target_entity_type_id_name", sa.String(), nullable=False, index=True
        ),
        sa.Column("definition", sa.Boolean(), nullable=False, default=False),
        sa.Column("occurrences", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(), nullable=False, index=True),
        sa.Column("active", sa.Boolean(), nullable=False, default=True),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "clustering",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
        sa.ForeignKeyConstraint(
            ["source_entity_type_id_name"], ["kg_entity_type.id_name"]
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_type_id_name"], ["kg_entity_type.id_name"]
        ),
    )

    # Create KGEntity table
    op.create_table(
        "kg_entity",
        sa.Column("id_name", sa.String(), primary_key=True, nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column("sub_type", sa.String(), nullable=True, index=True),
        sa.Column("document_id", sa.String(), nullable=True, index=True),
        sa.Column(
            "alternative_names",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("entity_type_id_name", sa.String(), nullable=False, index=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "keywords",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("occurrences", sa.Integer(), nullable=True),
        sa.Column(
            "acl", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"
        ),
        sa.Column("boosts", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("attributes", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        # Add clustering columns
        sa.Column("clustering_name", NullFilteredString, nullable=True),
        sa.Column("clustering_trigrams", postgresql.ARRAY(sa.String(3)), nullable=True),
        sa.ForeignKeyConstraint(["entity_type_id_name"], ["kg_entity_type.id_name"]),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
    )
    op.create_index("ix_entity_type_acl", "kg_entity", ["entity_type_id_name", "acl"])
    op.create_index(
        "ix_entity_name_search", "kg_entity", ["name", "entity_type_id_name"]
    )

    # Create KGEntityExtractionStaging table
    op.create_table(
        "kg_entity_extraction_staging",
        sa.Column("id_name", sa.String(), primary_key=True, nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False, index=True),
        sa.Column("sub_type", sa.String(), nullable=True, index=True),
        sa.Column("document_id", sa.String(), nullable=True, index=True),
        sa.Column(
            "alternative_names",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("entity_type_id_name", sa.String(), nullable=False, index=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "keywords",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("occurrences", sa.Integer(), nullable=True),
        sa.Column(
            "acl", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"
        ),
        sa.Column("boosts", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("attributes", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("clustering_name", NullFilteredString, nullable=True),
        sa.ForeignKeyConstraint(["entity_type_id_name"], ["kg_entity_type.id_name"]),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
    )
    op.create_index(
        "ix_entity_extraction_staging_acl",
        "kg_entity_extraction_staging",
        ["entity_type_id_name", "acl"],
    )
    op.create_index(
        "ix_entity_extraction_staging_name_search",
        "kg_entity_extraction_staging",
        ["name", "entity_type_id_name"],
    )

    # Create KGRelationship table
    op.create_table(
        "kg_relationship",
        sa.Column("id_name", sa.String(), nullable=False, index=True),
        sa.Column("source_node", sa.String(), nullable=False, index=True),
        sa.Column("target_node", sa.String(), nullable=False, index=True),
        sa.Column("source_node_type", sa.String(), nullable=False, index=True),
        sa.Column("target_node_type", sa.String(), nullable=False, index=True),
        sa.Column("source_document", sa.String(), nullable=True, index=True),
        sa.Column("type", sa.String(), nullable=False, index=True),
        sa.Column("relationship_type_id_name", sa.String(), nullable=False, index=True),
        sa.Column("occurrences", sa.Integer(), nullable=True),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["source_node"], ["kg_entity.id_name"]),
        sa.ForeignKeyConstraint(["target_node"], ["kg_entity.id_name"]),
        sa.ForeignKeyConstraint(["source_node_type"], ["kg_entity_type.id_name"]),
        sa.ForeignKeyConstraint(["target_node_type"], ["kg_entity_type.id_name"]),
        sa.ForeignKeyConstraint(["source_document"], ["document.id"]),
        sa.ForeignKeyConstraint(
            ["relationship_type_id_name"], ["kg_relationship_type.id_name"]
        ),
        sa.UniqueConstraint(
            "source_node",
            "target_node",
            "type",
            name="uq_kg_relationship_source_target_type",
        ),
        sa.PrimaryKeyConstraint("id_name", "source_document"),
    )
    op.create_index(
        "ix_kg_relationship_nodes", "kg_relationship", ["source_node", "target_node"]
    )

    # Create KGRelationshipExtractionStaging table
    op.create_table(
        "kg_relationship_extraction_staging",
        sa.Column("id_name", sa.String(), nullable=False, index=True),
        sa.Column("source_node", sa.String(), nullable=False, index=True),
        sa.Column("target_node", sa.String(), nullable=False, index=True),
        sa.Column("source_node_type", sa.String(), nullable=False, index=True),
        sa.Column("target_node_type", sa.String(), nullable=False, index=True),
        sa.Column("source_document", sa.String(), nullable=True, index=True),
        sa.Column("type", sa.String(), nullable=False, index=True),
        sa.Column("relationship_type_id_name", sa.String(), nullable=False, index=True),
        sa.Column("occurrences", sa.Integer(), nullable=True),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(
            ["source_node"], ["kg_entity_extraction_staging.id_name"]
        ),
        sa.ForeignKeyConstraint(
            ["target_node"], ["kg_entity_extraction_staging.id_name"]
        ),
        sa.ForeignKeyConstraint(["source_node_type"], ["kg_entity_type.id_name"]),
        sa.ForeignKeyConstraint(["target_node_type"], ["kg_entity_type.id_name"]),
        sa.ForeignKeyConstraint(["source_document"], ["document.id"]),
        sa.ForeignKeyConstraint(
            ["relationship_type_id_name"],
            ["kg_relationship_type_extraction_staging.id_name"],
        ),
        sa.UniqueConstraint(
            "source_node",
            "target_node",
            "type",
            name="uq_kg_relationship_extraction_staging_source_target_type",
        ),
        sa.PrimaryKeyConstraint("id_name", "source_document"),
    )
    op.create_index(
        "ix_kg_relationship_extraction_staging_nodes",
        "kg_relationship_extraction_staging",
        ["source_node", "target_node"],
    )

    # Create KGTerm table
    op.create_table(
        "kg_term",
        sa.Column("id_term", sa.String(), primary_key=True, nullable=False, index=True),
        sa.Column(
            "entity_types",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_search_term_entities", "kg_term", ["entity_types"])
    op.create_index("ix_search_term_term", "kg_term", ["id_term"])

    op.add_column(
        "document",
        sa.Column("kg_stage", sa.String(), nullable=True, index=True),
    )
    op.add_column(
        "document",
        sa.Column("kg_processing_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "connector",
        sa.Column(
            "kg_processing_enabled",
            sa.Boolean(),
            nullable=True,
            server_default="false",
        ),
    )

    # Create GIN index on clustering columns
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_entity_clustering_trigrams "
        "ON kg_entity USING GIN (clustering_trigrams)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_entity_extraction_clustering_trigrams "
        "ON kg_entity_extraction_staging USING GIN (clustering_name gin_trgm_ops)"
    )

    # Create trigger to update clustering columns if entity w/ doc_id is created
    alphanum_pattern = r"[^a-z0-9]+"
    op.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION update_kg_entity_clustering()
            RETURNS TRIGGER AS $$
            DECLARE
                doc_semantic_id text;
                cleaned_semantic_id text;
                max_length integer := 1000; -- Limit length for performance
            BEGIN
                -- Get semantic_id from document
                SELECT semantic_id INTO doc_semantic_id
                FROM document
                WHERE id = NEW.document_id;

                -- Clean the semantic_id with regex patterns and handle NULLs
                cleaned_semantic_id = regexp_replace(
                    lower(COALESCE(doc_semantic_id, NEW.name, '')),
                    '{alphanum_pattern}', '', 'g'
                );

                -- Truncate if too long for performance
                IF length(cleaned_semantic_id) > max_length THEN
                    cleaned_semantic_id = left(cleaned_semantic_id, max_length);
                END IF;

                -- Set clustering_name to cleaned version and generate trigrams
                NEW.clustering_name = cleaned_semantic_id;
                NEW.clustering_trigrams = show_trgm(cleaned_semantic_id);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION update_kg_entity_extraction_clustering()
            RETURNS TRIGGER AS $$
            DECLARE
                doc_semantic_id text;
            BEGIN
                -- Get semantic_id from document
                -- If no document is found, doc_semantic_id will be NULL and COALESCE will use NEW.name
                SELECT semantic_id INTO doc_semantic_id
                FROM document
                WHERE id = NEW.document_id;

                -- Set clustering_name to semantic_id
                NEW.clustering_name = lower(COALESCE(doc_semantic_id, NEW.name, ''));
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
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
                BEFORE INSERT
                ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION {function}();
            """
        )

    # Create trigger to update kg_entity clustering_name and its trigrams when document.clustering_name changes
    op.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION update_kg_entity_clustering_from_doc()
            RETURNS TRIGGER AS $$
            DECLARE
                cleaned_semantic_id text;
            BEGIN
                -- Clean the semantic_id with regex patterns
                -- If semantic_id is NULL, COALESCE will use empty string
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
    )
    op.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION update_kg_entity_extraction_clustering_from_doc()
            RETURNS TRIGGER AS $$
            BEGIN
                -- Update clustering name for all entities in staging referencing this document
                -- If semantic_id is NULL, COALESCE will use empty string
                UPDATE kg_entity_extraction_staging
                SET
                    clustering_name = lower(COALESCE(NEW.semantic_id, ''))
                WHERE document_id = NEW.id;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
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


def downgrade() -> None:

    if not MULTI_TENANT:
        # Drop temporary views
        conn = op.get_bind()
        kg_temp_views = [
            row[0]
            for row in conn.execute(
                text(
                    """
                SELECT table_name
                FROM INFORMATION_SCHEMA.views
                WHERE table_name like 'allowed_docs%';
                """
                )
            ).fetchall()
        ]
        for view in kg_temp_views:
            op.execute(f"DROP VIEW IF EXISTS {view}")

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

    # Drop index
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_kg_entity_clustering_trigrams")
    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS idx_kg_entity_extraction_clustering_trigrams"
    )

    # Drop tables in reverse order of creation to handle dependencies
    op.drop_table("kg_term")
    op.drop_table("kg_relationship")
    op.drop_table("kg_entity")
    op.drop_table("kg_relationship_type")
    op.drop_table("kg_relationship_extraction_staging")
    op.drop_table("kg_relationship_type_extraction_staging")
    op.drop_table("kg_entity_extraction_staging")
    op.drop_table("kg_entity_type")
    op.drop_column("connector", "kg_processing_enabled")
    op.drop_column("document", "kg_stage")
    op.drop_column("document", "kg_processing_time")
    op.drop_table("kg_config")

    if not MULTI_TENANT:
        # Drop read-only db user here only in single tenant mode. For multi-tenant mode,
        # the user is dropped in the alembic_tenants migration.

        op.execute(
            text(
                f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{DB_READONLY_USER}') THEN
                    -- First revoke all privileges from the database
                    EXECUTE format('REVOKE ALL ON DATABASE %I FROM %I', current_database(), '{DB_READONLY_USER}');
                    -- Then revoke all privileges from the public schema
                    EXECUTE format('REVOKE ALL ON SCHEMA public FROM %I', '{DB_READONLY_USER}');
                    -- Then drop the user
                    EXECUTE format('DROP USER %I', '{DB_READONLY_USER}');
                END IF;
            END
            $$;
        """
            )
        )
