"""add in_progress_results to credential_capability_report

The results-so-far of the run attempt that owns the row's RUNNING mark, written
after each check completes so a poller can read per-check status mid-run.
``report`` keeps holding the last COMPLETED run only. NULL until an attempt
records a result; cleared by the next RUNNING mark and by every completion
write.

Revision ID: 9084be85e0ad
Revises: ad99acb9be41
Create Date: 2026-09-22 17:09:57.663881

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9084be85e0ad"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credential_capability_report",
        sa.Column("in_progress_results", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("credential_capability_report", "in_progress_results")
