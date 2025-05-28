"""Add chat_message__standard_answer table

Revision ID: c5eae4a75a1b
Revises: 0f7ff6d75b57
Create Date: 2025-01-15 14:08:49.688998

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c5eae4a75a1b"
down_revision = "0f7ff6d75b57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_message__standard_answer",
        sa.Column("chat_message_id", sa.Integer(), nullable=False),
        sa.Column("standard_answer_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_message_id"],
            ["chat_message.id"],
        ),
        sa.ForeignKeyConstraint(
            ["standard_answer_id"],
            ["standard_answer.id"],
        ),
        sa.PrimaryKeyConstraint("chat_message_id", "standard_answer_id"),
    )


def downgrade() -> None:
    op.drop_table("chat_message__standard_answer")
