"""add_file_ids_to_research_agent_iteration_sub_step

Revision ID: f184096b67bc
Revises: c7e9f4a3b2d1
Create Date: 2025-11-14 18:59:15.056114

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f184096b67bc"
down_revision = "c7e9f4a3b2d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add file_ids column to research_agent_iteration_sub_step table for storing file references from tools."""
    op.add_column(
        "research_agent_iteration_sub_step",
        sa.Column(
            "file_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove file_ids column from research_agent_iteration_sub_step table."""
    op.drop_column("research_agent_iteration_sub_step", "file_ids")
