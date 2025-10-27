"""drop deprecated is_positive column

Revision ID: 70875b3ff477
Revises: 67676bcd28aa
Create Date: 2025-10-27 14:07:24.113399

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "70875b3ff477"
down_revision = "67676bcd28aa"
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
