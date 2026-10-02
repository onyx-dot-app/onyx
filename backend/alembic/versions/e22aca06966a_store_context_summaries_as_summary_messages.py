"""Store context summaries as SUMMARY chat messages.

Revision ID: e22aca06966a
Revises: b3e7c1d9a4f2
Create Date: 2026-10-02 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "e22aca06966a"
down_revision = "b3e7c1d9a4f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "chat_message",
        "message_type",
        existing_type=sa.String(9),
        type_=sa.String(32),
        existing_nullable=False,
    )
    op.execute("""
        UPDATE chat_message SET message_type = 'SUMMARY'
        WHERE message_type = 'ASSISTANT' AND last_summarized_message_id IS NOT NULL
    """)
    op.add_column(
        "chat_message",
        sa.Column("summary_covered_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chat_message",
        sa.Column("summary_covered_digest", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.execute("DELETE FROM chat_message WHERE summary_covered_count IS NOT NULL")
    op.execute("""
        UPDATE chat_message SET message_type = 'ASSISTANT'
        WHERE message_type = 'SUMMARY'
    """)
    op.drop_column("chat_message", "summary_covered_digest")
    op.drop_column("chat_message", "summary_covered_count")
    op.alter_column(
        "chat_message",
        "message_type",
        existing_type=sa.String(32),
        type_=sa.String(9),
        existing_nullable=False,
    )
