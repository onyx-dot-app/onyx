"""add subscription tables

Revision ID: 13a84b9c2d5f
Revises: 12h73u00mcwb
Create Date: 2025-12-12 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "13a84b9c2d5f"
down_revision = "12h73u00mcwb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create subscription_registrations table
    op.create_table(
        "subscription_registrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "doc_extraction_contexts",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "search_questions",
            postgresql.ARRAY(sa.String()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
    )

    # Create subscription_results table
    op.create_table(
        "subscription_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column(
            "notifications",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
    )


def downgrade() -> None:
    op.drop_table("subscription_results")
    op.drop_table("subscription_registrations")
