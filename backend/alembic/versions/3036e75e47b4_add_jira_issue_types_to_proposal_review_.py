"""add jira_issue_types to proposal_review_config

Revision ID: 3036e75e47b4
Revises: ce2aa573d445
Create Date: 2026-05-05 10:25:29.820641

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3036e75e47b4"
down_revision = "ce2aa573d445"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "proposal_review_config",
        sa.Column("jira_issue_types", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proposal_review_config", "jira_issue_types")
