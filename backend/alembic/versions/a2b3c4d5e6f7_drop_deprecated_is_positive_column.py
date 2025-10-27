"""drop deprecated is_positive column

Revision ID: a2b3c4d5e6f7
Revises: f3adfff20605
Create Date: 2025-10-27 15:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f7"
down_revision = "f3adfff20605"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the deprecated is_positive column
    op.drop_column("chat_feedback", "is_positive")


def downgrade() -> None:
    # Re-add is_positive column
    op.add_column(
        "chat_feedback", sa.Column("is_positive", sa.Boolean(), nullable=True)
    )

    # Backfill from feedback enum
    op.execute(
        """
        UPDATE chat_feedback
        SET is_positive = CASE
            WHEN feedback = 'like' THEN TRUE
            WHEN feedback = 'dislike' THEN FALSE
            ELSE NULL
        END
    """
    )
