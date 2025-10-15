"""add_is_web_fetch_and_queries_to_research_agent_iteration_sub_step

Revision ID: a3953b9bffda
Revises: 96a5702df6aa
Create Date: 2025-10-14 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a3953b9bffda"
down_revision = "96a5702df6aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_web_fetch column
    op.add_column(
        "research_agent_iteration_sub_step",
        sa.Column("is_web_fetch", sa.Boolean(), nullable=True),
    )

    # Add queries column
    op.add_column(
        "research_agent_iteration_sub_step",
        sa.Column("queries", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_agent_iteration_sub_step", "queries")
    op.drop_column("research_agent_iteration_sub_step", "is_web_fetch")
