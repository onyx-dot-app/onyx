"""agent_metric_table_renames__agent__

Revision ID: 9787be927e58
Revises: bceb76d618ec
Create Date: 2025-01-06 11:01:44.210160

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "9787be927e58"
down_revision = "bceb76d618ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename table from agent_search_metrics to agent__search_metrics
    op.rename_table("agent_search_metrics", "agent__search_metrics")


def downgrade() -> None:
    # Rename table back from agent__search_metrics to agent_search_metrics
    op.rename_table("agent__search_metrics", "agent_search_metrics")
