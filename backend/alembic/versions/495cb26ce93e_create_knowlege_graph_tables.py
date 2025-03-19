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
    # Create kg_entity table
    op.create_table(
        "kg_entity",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "alternative_names",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("type", sa.String(), nullable=False),
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
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_type_acl", "kg_entity", ["type", "acl"])
    op.create_index("ix_entity_name_search", "kg_entity", ["name", "type"])
    op.create_index("ix_kg_entity_id", "kg_entity", ["id"])

    # Create kg_relationship table
    op.create_table(
        "kg_relationship",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_node", sa.String(), nullable=False),
        sa.Column("target_node", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_node"],
            ["kg_entity.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_node"],
            ["kg_entity.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_node",
            "target_node",
            "type",
            name="uq_kg_relationship_source_target_type",
        ),
    )
    op.create_index("ix_kg_relationship_type", "kg_relationship", ["type"])
    op.create_index(
        "ix_kg_relationship_nodes", "kg_relationship", ["source_node", "target_node"]
    )
    op.create_index("ix_kg_relationship_id", "kg_relationship", ["id"])

    # Create kg_term table
    op.create_table(
        "kg_term",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("term", sa.String(), nullable=False),
        sa.Column(
            "entity_types",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_term_entities", "kg_term", ["entity_types"])
    op.create_index("ix_search_term_term", "kg_term", ["term"])
    op.create_index("ix_kg_term_id", "kg_term", ["id"])
    op.create_unique_constraint("uq_kg_term_term", "kg_term", ["term"])


def downgrade() -> None:
    # Drop tables in reverse order of creation (respecting foreign key constraints)
    op.drop_table("kg_term")
    op.drop_table("kg_relationship")
    op.drop_table("kg_entity")
