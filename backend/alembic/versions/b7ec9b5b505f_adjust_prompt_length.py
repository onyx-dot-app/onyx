"""adjust prompt length

Revision ID: b7ec9b5b505f
Revises: abbfec3a5ac5
Create Date: 2025-09-10 18:51:15.629197

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7ec9b5b505f"
down_revision = "abbfec3a5ac5"
branch_labels = None
depends_on = None


MAX_PROMPT_LENGTH = 5_000_000


def upgrade() -> None:
    # NOTE: need to run this since the previous migration PREVIOUSLY set the length to 8000
    op.alter_column(
        "persona",
        "system_prompt",
        existing_type=sa.String(length=8000),
        type_=sa.String(length=MAX_PROMPT_LENGTH),
        existing_nullable=False,
    )
    op.alter_column(
        "persona",
        "task_prompt",
        existing_type=sa.String(length=8000),
        type_=sa.String(length=MAX_PROMPT_LENGTH),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Downgrade not necessary
    pass
