"""add calling_agent_name to research_agent_iteration_sub_step

Revision ID: 23f0b9b49965
Revises: 09995b8811eb
Create Date: 2025-10-27 17:55:10.802310

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "23f0b9b49965"
down_revision = "09995b8811eb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_agent_iteration_sub_step",
        sa.Column("calling_agent_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_agent_iteration_sub_step", "calling_agent_name")
