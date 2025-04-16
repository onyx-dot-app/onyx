"""Add Chat Feedback

Revision ID: e0a68a81d434
Revises: ae62505e3acc
Create Date: 2023-10-04 20:22:33.380286

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e0a68a81d434"
down_revision = "ae62505e3acc"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "chat_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_message_chat_session_id", sa.Integer(), nullable=False),
        sa.Column("chat_message_message_number", sa.Integer(), nullable=False),
        sa.Column("chat_message_edit_number", sa.Integer(), nullable=False),
        sa.Column("is_positive", sa.Boolean(), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            [
                "chat_message_chat_session_id",
                "chat_message_message_number",
                "chat_message_edit_number",
            ],
            [
                "chat_message.chat_session_id",
                "chat_message.message_number",
                "chat_message.edit_number",
            ],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("chat_feedback")
