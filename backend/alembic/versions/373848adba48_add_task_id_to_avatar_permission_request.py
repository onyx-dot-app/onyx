"""add_task_id_to_avatar_permission_request

Revision ID: 373848adba48
Revises: a1b2c3d4e5f6
Create Date: 2025-12-11 18:41:18.678042

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "373848adba48"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatar_permission_request",
        sa.Column("task_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_avatar_permission_request_task_id",
        "avatar_permission_request",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_avatar_permission_request_task_id",
        table_name="avatar_permission_request",
    )
    op.drop_column("avatar_permission_request", "task_id")
