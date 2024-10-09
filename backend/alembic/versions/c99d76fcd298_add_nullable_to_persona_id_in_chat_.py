"""add nullable to persona id in Chat Session

Revision ID: c99d76fcd298
Revises: 5c7fdadae813
Create Date: 2024-07-09 19:27:01.579697

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c99d76fcd298"
down_revision = "5c7fdadae813"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "chat_session", "persona_id", existing_type=sa.INTEGER(), nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "chat_session",
        "persona_id",
        existing_type=sa.INTEGER(),
        nullable=False,
    )
