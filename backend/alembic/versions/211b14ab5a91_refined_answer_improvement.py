"""refined answer improvement

Revision ID: 211b14ab5a91
Revises: 925b58bd75b6
Create Date: 2025-01-24 14:05:03.334309

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "211b14ab5a91"
down_revision = "925b58bd75b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column(
            "refined_answer_improvement",
            sa.Boolean(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "refined_answer_improvement")
