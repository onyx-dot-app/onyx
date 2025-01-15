"""agent_tracking

Revision ID: 98a5008d8711
Revises: 027381bce97c
Create Date: 2025-01-04 14:41:52.732238

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "98a5008d8711"
down_revision = "027381bce97c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_search_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column("agent_type", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("base_duration_s", sa.Float(), nullable=False),
        sa.Column("full_duration_s", sa.Float(), nullable=False),
        sa.Column("base_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("refined_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("all_metrics", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("agent_search_metrics")
