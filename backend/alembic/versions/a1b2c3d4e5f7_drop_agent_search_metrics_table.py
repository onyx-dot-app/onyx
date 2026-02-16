"""drop agent_search_metrics table

Revision ID: a1b2c3d4e5f7
Revises: 73e9983e5091
Create Date: 2026-01-17

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f7"
down_revision = "73e9983e5091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("agent__search_metrics")


def downgrade() -> None:
    op.create_table(
        "agent__search_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column("agent_type", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("base_duration_s", sa.Float(), nullable=False),
        sa.Column("full_duration_s", sa.Float(), nullable=False),
        sa.Column("base_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("refined_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("all_metrics", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
