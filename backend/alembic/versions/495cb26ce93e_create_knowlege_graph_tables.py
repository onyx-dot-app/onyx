"""create knowlege graph tables

Revision ID: 495cb26ce93e
Revises: 6a804aeb4830
Create Date: 2025-03-19 08:51:14.341989

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "495cb26ce93e"
down_revision = "6a804aeb4830"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kg_entity_type",
        sa.Column("id_name", sa.String(), primary_key=True, nullable=False, index=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("grounding", sa.String(), nullable=False),
        sa.Column("clustering", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "classification_requirements",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
        sa.Column("cluster_count", sa.Integer(), nullable=True),
        sa.Column(
            "extraction_sources", postgresql.JSONB, nullable=False, server_default="{}"
        ),
        sa.Column("active", sa.Boolean(), nullable=False, default=False),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("grounded_source_name", sa.String(), nullable=True, unique=True),
        sa.Column(
            "ge_determine_instructions", postgresql.ARRAY(sa.String()), nullable=True
        ),
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
        sa.Column("clustering", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("cluster_count", sa.Integer(), nullable=True),
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
        sa.Column("cluster_count", sa.Integer(), nullable=True),
        sa.Column(
            "acl", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"
        ),
        sa.Column("boosts", postgresql.JSONB, nullable=False, server_default="{}"),
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

    # Create KGRelationship table
    op.create_table(
        "kg_relationship",
        sa.Column("id_name", sa.String(), primary_key=True, nullable=False, index=True),
        sa.Column("source_node", sa.String(), nullable=False, index=True),
        sa.Column("target_node", sa.String(), nullable=False, index=True),
        sa.Column("type", sa.String(), nullable=False, index=True),
        sa.Column("relationship_type_id_name", sa.String(), nullable=False, index=True),
        sa.Column("cluster_count", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["relationship_type_id_name"], ["kg_relationship_type.id_name"]
        ),
        sa.UniqueConstraint(
            "source_node",
            "target_node",
            "type",
            name="uq_kg_relationship_source_target_type",
        ),
    )
    op.create_index(
        "ix_kg_relationship_nodes", "kg_relationship", ["source_node", "target_node"]
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
        sa.Column("kg_processed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "document",
        sa.Column("kg_data", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "connector",
        sa.Column(
            "kg_extraction_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    op.add_column(
        "document_by_connector_credential_pair",
        sa.Column("has_been_kg_processed", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    # Drop tables in reverse order of creation to handle dependencies
    op.drop_table("kg_term")
    op.drop_table("kg_relationship")
    op.drop_table("kg_entity")
    op.drop_table("kg_relationship_type")
    op.drop_table("kg_entity_type")
    op.drop_column("connector", "kg_extraction_enabled")
    op.drop_column("document_by_connector_credential_pair", "has_been_kg_processed")
    op.drop_column("document", "kg_data")
    op.drop_column("document", "kg_processed")
