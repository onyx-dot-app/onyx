"""create knowlege graph tables

Revision ID: 495cb26ce93e
Revises: 3781a5eb12cb
Create Date: 2025-03-19 08:51:14.341989

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "495cb26ce93e"
down_revision = "3781a5eb12cb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create kg_entity_type table
    op.create_table(
        "kg_entity_type",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("name", sa.String(), nullable=False, unique=True),  # unique=True here
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("grounding", sa.String(), nullable=False),
        sa.Column(
            "extraction_sources",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("active", sa.Boolean(), nullable=False, default=False),
        sa.Column(
            "clustering", postgresql.JSONB(), nullable=False, server_default="{}"
        ),  # Add this line
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_kg_entity_type_id", "kg_entity_type", ["id"])
    op.create_index("ix_kg_entity_type_name", "kg_entity_type", ["name"])

    # Create kg_relationship_type table
    op.create_table(
        "kg_relationship_type",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "source_entity_type_id",
            sa.Integer(),
            sa.ForeignKey("kg_entity_type.id"),
            nullable=False,
        ),  # Integer type
        sa.Column(
            "target_entity_type_id",
            sa.Integer(),
            sa.ForeignKey("kg_entity_type.id"),
            nullable=False,
        ),  # Integer type
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, default=True),
        sa.Column(
            "definition", sa.Boolean(), nullable=False, server_default="false"
        ),  # Add this line
        sa.Column(
            "clustering", postgresql.JSONB(), nullable=False, server_default="{}"
        ),  # Add this line
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "name",
            "source_entity_type_id",
            "target_entity_type_id",
            name="uq_kg_relationship_type_name_types",
        ),
    )
    op.create_index("ix_kg_relationship_type_id", "kg_relationship_type", ["id"])
    op.create_index("ix_kg_relationship_type_name", "kg_relationship_type", ["name"])
    op.create_index(
        "ix_kg_relationship_type_source_entity_type_id",
        "kg_relationship_type",
        ["source_entity_type_id"],
    )
    op.create_index(
        "ix_kg_relationship_type_target_entity_type_id",
        "kg_relationship_type",
        ["target_entity_type_id"],
    )
    op.create_index("ix_kg_relationship_type_type", "kg_relationship_type", ["type"])

    # Create kg_entity table
    op.create_table(
        "kg_entity",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column(
            "alternative_names",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "entity_type_id",
            sa.Integer(),
            sa.ForeignKey("kg_entity_type.id"),
            nullable=False,
        ),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "keywords",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "acl", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"
        ),
        sa.Column("boosts", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_kg_entity_id", "kg_entity", ["id"])
    op.create_index("ix_kg_entity_name", "kg_entity", ["name"])
    op.create_index("ix_kg_entity_document_id", "kg_entity", ["document_id"])
    op.create_index("ix_kg_entity_entity_type_id", "kg_entity", ["entity_type_id"])
    op.create_index("ix_entity_type_acl", "kg_entity", ["entity_type_id", "acl"])
    op.create_index("ix_entity_name_search", "kg_entity", ["name", "entity_type_id"])

    # Create kg_relationship table
    op.create_table(
        "kg_relationship",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "source_node", sa.String(), sa.ForeignKey("kg_entity.id"), nullable=False
        ),
        sa.Column(
            "target_node", sa.String(), sa.ForeignKey("kg_entity.id"), nullable=False
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column(
            "relationship_type_id",
            sa.Integer(),
            sa.ForeignKey("kg_relationship_type.id"),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "source_node",
            "target_node",
            "type",
            name="uq_kg_relationship_source_target_type",
        ),
    )
    op.create_index("ix_kg_relationship_id", "kg_relationship", ["id"])
    op.create_index(
        "ix_kg_relationship_source_node", "kg_relationship", ["source_node"]
    )
    op.create_index(
        "ix_kg_relationship_target_node", "kg_relationship", ["target_node"]
    )
    op.create_index("ix_kg_relationship_type", "kg_relationship", ["type"])
    op.create_index(
        "ix_kg_relationship_nodes", "kg_relationship", ["source_node", "target_node"]
    )

    # Create kg_term table
    op.create_table(
        "kg_term",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("term", sa.String(), nullable=False, unique=True),
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
            nullable=False,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_kg_term_id", "kg_term", ["id"])
    op.create_index("ix_kg_term_term", "kg_term", ["term"])
    op.create_index("ix_search_term_entities", "kg_term", ["entity_types"])
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
