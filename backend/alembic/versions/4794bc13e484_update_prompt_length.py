"""update prompt length

Revision ID: 4794bc13e484
Revises: 30274019439d
Create Date: 2025-04-02 11:26:36.180328

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4794bc13e484"
down_revision = "30274019439d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "prompt",
        "system_prompt",
        existing_type=sa.TEXT(),
        type_=sa.String(length=1000000),
        existing_nullable=False,
    )
    op.alter_column(
        "prompt",
        "task_prompt",
        existing_type=sa.TEXT(),
        type_=sa.String(length=1000000),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "prompt",
        "system_prompt",
        existing_type=sa.String(length=1000000),
        type_=sa.TEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        "prompt",
        "task_prompt",
        existing_type=sa.String(length=1000000),
        type_=sa.TEXT(),
        existing_nullable=False,
    )
