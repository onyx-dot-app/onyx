"""add chat session specific temperature override

Revision ID: 2f80c6a2550f
Revises: 33ea50e88f24
Create Date: 2025-01-31 10:30:27.289646

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2f80c6a2550f"
down_revision = "33ea50e88f24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_session", sa.Column("temperature_override", sa.Float(), nullable=True)
    )
    op.add_column(
        "user",
        sa.Column(
            "temperature_override_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_session", "temperature_override")
    op.drop_column("user", "temperature_override_enabled")
