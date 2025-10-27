"""refactor chat feedback to use enum

Revision ID: f3adfff20605
Revises: 09995b8811eb
Create Date: 2025-10-27 13:11:50.485341

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f3adfff20605"
down_revision = "09995b8811eb"
branch_labels = None
depends_on = None

# Define the ChatMessageFeedback enum type (for message-level feedback)
# Note: ChatSessionFeedback enum will be created in Stage 2a
chat_message_feedback_enum = postgresql.ENUM(
    "like", "dislike", name="chatmessagefeedback", create_type=True
)


def upgrade() -> None:
    # 1. Create the ChatMessageFeedback enum type in PostgreSQL
    chat_message_feedback_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add new feedback column (nullable)
    op.add_column(
        "chat_feedback",
        sa.Column("feedback", chat_message_feedback_enum, nullable=True),
    )

    # 3. Backfill existing data from is_positive to feedback
    op.execute(
        """
        UPDATE chat_feedback
        SET feedback = CASE
            WHEN is_positive = TRUE THEN 'like'::chatmessagefeedback
            WHEN is_positive = FALSE THEN 'dislike'::chatmessagefeedback
            ELSE NULL
        END
    """
    )

    # Note: is_positive column is kept for rollback safety
    # It will be removed in Stage 3


def downgrade() -> None:
    # Drop the new feedback column
    # Note: Any feedback data created after upgrade will be lost
    # This is acceptable per the constraints
    op.drop_column("chat_feedback", "feedback")

    # Drop the enum type
    chat_message_feedback_enum.drop(op.get_bind(), checkfirst=True)
