"""Task Tracking

Revision ID: 78dbe7e38469
Revises: 7ccea01261f6
Create Date: 2023-10-15 23:40:50.593262

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "78dbe7e38469"
down_revision = "7ccea01261f6"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "task_queue_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "STARTED",
                "SUCCESS",
                "FAILURE",
                name="taskstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "register_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("task_queue_jobs")
