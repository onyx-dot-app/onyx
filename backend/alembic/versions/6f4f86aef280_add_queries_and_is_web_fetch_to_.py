"""add queries and is web fetch to iteration answer

Revision ID: 6f4f86aef280
Revises: 03d710ccf29c
Create Date: 2025-10-14 18:08:30.920123

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "6f4f86aef280"
down_revision = "03d710ccf29c"
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
