"""add_is_web_fetch_to_research_agent_iteration_sub_step

Revision ID: 7b8602f1c50e
Revises: 96a5702df6aa
Create Date: 2025-10-13 16:27:59.324756

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7b8602f1c50e"
down_revision = "96a5702df6aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_agent_iteration_sub_step",
        sa.Column("is_web_fetch", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_agent_iteration_sub_step", "is_web_fetch")
