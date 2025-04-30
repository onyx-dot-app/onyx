"""create knowlege graph tables

Revision ID: 495cb26ce93e
Revises: 5c448911b12f
Create Date: 2025-03-19 08:51:14.341989

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from passlib.pwd import genword
from passlib.exc import PasswordSizeError
from sqlalchemy import text

from onyx.kg.configuration import KG_READONLY_DB_USER, KG_READONLY_DB_PASSWORD


# revision identifiers, used by Alembic.
revision = "495cb26ce93e"
down_revision = "5c448911b12f"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # Create a new permission-less user to be later used for knowledge graph queries.
    # The user will later get temporary read priviledges for a specific view that will be
    # ad hoc generated specific to a knowledge graph query.
    #
    # Note: in order for the migration to run, the KG_READONLY_DB_USER and KG_READONLY_DB_PASSWORD
    # environment variables MUST be set. Otherwise, an exception will be raised.

    if not (KG_READONLY_DB_USER and KG_READONLY_DB_PASSWORD):

        raise Exception("KG_READONLY_DB_USER or KG_READONLY_DB_PASSWORD is not set")

    try:
        # Validate password length and complexity
        genword(
            length=13, charset="ascii_72"
        )  # This will raise PasswordSizeError if too short
        # Additional checks can be added here if needed
    except PasswordSizeError:
        raise Exception("KG_READONLY_DB_PASSWORD is too short or too weak")

    op.execute(
        text(
            f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{KG_READONLY_DB_USER}') THEN
                EXECUTE format('CREATE USER %I WITH PASSWORD %L', '{KG_READONLY_DB_USER}', '{KG_READONLY_DB_PASSWORD}');
                -- Explicitly revoke all privileges including CONNECT
                EXECUTE format('REVOKE ALL ON DATABASE %I FROM %I', current_database(), '{KG_READONLY_DB_USER}');
            END IF;
        END
        $$;
    """
        )
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
        sa.Column("occurences", sa.Integer(), nullable=True),
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
        sa.Column(
            "grounded_source_subtypes", postgresql.ARRAY(sa.String()), nullable=True
        ),
        sa.Column("entity_values", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("ge_grounding_signature", sa.String(), nullable=True),
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
        sa.Column("occurences", sa.Integer(), nullable=True),
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
        sa.Column("occurences", sa.Integer(), nullable=True),
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
        sa.Column("occurences", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["entity_type_id_name"], ["kg_entity_type.id_name"]),
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
        sa.Column("occurences", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["entity_type_id_name"], ["kg_entity_type.id_name"]),
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
        sa.Column("occurences", sa.Integer(), nullable=True),
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
        sa.Column("occurences", sa.Integer(), nullable=True),
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
        "connector",
        sa.Column(
            "kg_processing_enabled",
            sa.Boolean(),
            nullable=True,
            server_default="false",
        ),
    )

    op.add_column(
        "document_by_connector_credential_pair",
        sa.Column("kg_stage", sa.String(), nullable=True, index=True),
    )


def downgrade() -> None:
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
    op.drop_column("document_by_connector_credential_pair", "kg_stage")
    op.drop_column("document", "kg_stage")

    op.execute(
        text(
            f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{KG_READONLY_DB_USER}') THEN
                EXECUTE format('DROP USER %I', '{KG_READONLY_DB_USER}');
            END IF;
        END
        $$;
    """
        )
    )
