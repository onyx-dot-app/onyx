"""add_queries_field_to_research_agent_iteration_sub_step

Revision ID: da032f42b16d
Revises: 7b8602f1c50e
Create Date: 2025-10-13 17:50:38.964235

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "da032f42b16d"
down_revision = "7b8602f1c50e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_agent_iteration_sub_step",
        sa.Column("queries", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_agent_iteration_sub_step", "queries")
