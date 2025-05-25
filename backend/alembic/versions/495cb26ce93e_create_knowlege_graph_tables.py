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
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{DB_READONLY_USER}') THEN
                    EXECUTE format('CREATE USER %I WITH PASSWORD %L', '{DB_READONLY_USER}', '{DB_READONLY_PASSWORD}');
                    -- Explicitly revoke all privileges including CONNECT
                    EXECUTE format('REVOKE ALL ON DATABASE %I FROM %I', current_database(), '{DB_READONLY_USER}');
                    -- Grant only the CONNECT privilege
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
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_entity_clustering_trigrams "
        "ON kg_entity USING GIN (clustering_trigrams)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kg_entity_extraction_clustering_trigrams "
        "ON kg_entity_extraction_staging USING GIN (clustering_name gin_trgm_ops)"
    )


def downgrade() -> None:

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
