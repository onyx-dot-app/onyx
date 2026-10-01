"""Add flow_run.resume_at for delayed runs

Revision ID: b03621dce5db
Revises: 23a2284581d0
Create Date: 2026-06-03 17:12:44.907531

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b03621dce5db"
down_revision = "23a2284581d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_run", sa.Column("resume_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Partial: only a run parked on a delay carries a resume time, so the
    # sweep's index stays the size of what is waiting rather than of all
    # run history.
    op.create_index(
        "ix_flow_run_resume_at",
        "flow_run",
        ["resume_at"],
        unique=False,
        postgresql_where=sa.text("resume_at IS NOT NULL"),
    )


def downgrade() -> None:
    # A parked run cannot be represented without the column, so fail those
    # rather than leaving them waiting for a sweep that can no longer see them.
    op.execute(
        "UPDATE flow_run SET status = 'FAILED', "
        "error_class = 'node_exception', "
        "error_detail = 'run was waiting on a delay when the schema was "
        "rolled back' WHERE status = 'AWAITING_DELAY'"
    )
    op.drop_index("ix_flow_run_resume_at", table_name="flow_run")
    op.drop_column("flow_run", "resume_at")
