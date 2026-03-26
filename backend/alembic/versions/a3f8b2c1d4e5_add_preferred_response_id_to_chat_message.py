"""add preferred_response_id and model_display_name to chat_message

Revision ID: a3f8b2c1d4e5
Create Date: 2026-03-22

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a3f8b2c1d4e5"
down_revision = "25a5501dc766"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column(
            "preferred_response_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "chat_message",
        sa.Column("model_display_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "model_display_name")
    op.drop_column("chat_message", "preferred_response_id")
