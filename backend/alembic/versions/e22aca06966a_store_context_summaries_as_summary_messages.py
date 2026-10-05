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
    op.drop_constraint(
        "chat_message_last_summarized_message_id_fkey",
        "chat_message",
        type_="foreignkey",
    )
    op.alter_column(
        "chat_message",
        "last_summarized_message_id",
        existing_type=sa.Integer(),
        type_=sa.String(),
        existing_nullable=True,
        postgresql_using="'chat:' || last_summarized_message_id::text",
    )


def downgrade() -> None:
    # Integer cutoffs can reference only complete chat-message rows.
    op.execute("""
        DELETE FROM chat_message AS summary
        WHERE message_type = 'SUMMARY' AND last_summarized_message_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM chat_message AS covered
              WHERE summary.last_summarized_message_id = 'chat:' || covered.id::text
          )
    """)
    op.execute("""
        UPDATE chat_message AS summary
        SET last_summarized_message_id = covered.id::text
        FROM chat_message AS covered
        WHERE summary.last_summarized_message_id = 'chat:' || covered.id::text
    """)
    op.alter_column(
        "chat_message",
        "last_summarized_message_id",
        existing_type=sa.String(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="last_summarized_message_id::integer",
    )
    op.create_foreign_key(
        "chat_message_last_summarized_message_id_fkey",
        "chat_message",
        "chat_message",
        ["last_summarized_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("""
        UPDATE chat_message SET message_type = 'ASSISTANT'
        WHERE message_type = 'SUMMARY'
    """)
    op.alter_column(
        "chat_message",
        "message_type",
        existing_type=sa.String(32),
        type_=sa.String(9),
        existing_nullable=False,
    )
