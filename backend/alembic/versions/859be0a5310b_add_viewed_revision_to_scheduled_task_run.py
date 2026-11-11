"""add viewed revisions to scheduled_task_run

`version` advances each time a run reaches a status with results.
`viewed_revision` is the highest version the task owner opened. Existing
runs keep version 0, so they start as viewed.

Revision ID: 859be0a5310b
Revises: 3e30a81ec3bd
Create Date: 2026-10-30 10:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "859be0a5310b"
down_revision = "3e30a81ec3bd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_task_run",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scheduled_task_run",
        sa.Column("viewed_revision", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheduled_task_run", "viewed_revision")
    op.drop_column("scheduled_task_run", "version")
