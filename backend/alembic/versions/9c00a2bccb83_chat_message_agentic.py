"""chat_message_agentic

Revision ID: 9c00a2bccb83
Revises: b7a7eee5aa15
Create Date: 2025-02-17 11:15:43.081150

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c00a2bccb83"
down_revision = "b7a7eee5aa15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # First add the column as nullable
    op.add_column("chat_message", sa.Column("is_agentic", sa.Boolean(), nullable=True))

    # Update existing rows based on presence of SubQuestions
    op.execute(
        """
        UPDATE chat_message
        SET is_agentic = EXISTS (
            SELECT 1
            FROM agent__sub_question
            WHERE agent__sub_question.primary_question_id = chat_message.id
        )
        WHERE is_agentic IS NULL
    """
    )

    # Make the column non-nullable with a default value of False
    op.alter_column(
        "chat_message", "is_agentic", nullable=False, server_default=sa.text("false")
    )


def downgrade() -> None:
    op.drop_column("chat_message", "is_agentic")
