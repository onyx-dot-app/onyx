"""add failed_rules to proposal_review_run

Revision ID: ce2aa573d445
Revises: 61ea78857c97
Create Date: 2026-04-14 16:34:57.276707

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ce2aa573d445"
down_revision = "61ea78857c97"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "proposal_review_run",
        sa.Column(
            "failed_rules",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("proposal_review_run", "failed_rules")
