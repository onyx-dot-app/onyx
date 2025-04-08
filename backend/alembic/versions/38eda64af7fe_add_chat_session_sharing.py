"""Add chat session sharing

Revision ID: 38eda64af7fe
Revises: 776b3bbe9092
Create Date: 2024-03-27 19:41:29.073594

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "38eda64af7fe"
down_revision = "776b3bbe9092"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "chat_session",
        sa.Column(
            "shared_status",
            sa.Enum(
                "PUBLIC",
                "PRIVATE",
                name="chatsessionsharedstatus",
                native_enum=False,
            ),
            nullable=True,
        ),
    )
    op.execute("UPDATE chat_session SET shared_status='PRIVATE'")
    op.alter_column(
        "chat_session",
        "shared_status",
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("chat_session", "shared_status")
