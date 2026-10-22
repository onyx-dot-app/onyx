"""add run_deadline_at to credential_capability_report

When the RUNNING mark of a stored capability-check run expires. The worker
pushes it forward as checks finish; a mark past it is a dead run. NULL on a
RUNNING row (a pre-migration mark) reads as expired.

Revision ID: b209881eaf72
Revises: c5178de73522
Create Date: 2026-10-21 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b209881eaf72"
down_revision = "c5178de73522"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credential_capability_report",
        sa.Column("run_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("credential_capability_report", "run_deadline_at")
