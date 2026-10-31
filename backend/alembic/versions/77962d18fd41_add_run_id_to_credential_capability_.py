"""add run_id to credential_capability_report

The id of the run attempt that owns the row's lifecycle mark. Terminal writes
from the check-runner task are fenced on it, so a superseded attempt can never
mislabel its successor's row. NULL means no attempt owns the row (recorder
writes and pre-migration rows); the fenced writers never match NULL.

Revision ID: 77962d18fd41
Revises: 34fe28843029
Create Date: 2026-08-31 17:30:10.799949

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "77962d18fd41"
down_revision = "34fe28843029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credential_capability_report",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("credential_capability_report", "run_id")
