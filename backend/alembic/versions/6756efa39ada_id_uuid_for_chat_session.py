"""Migrate chat_session and chat_message tables to use UUID primary keys

Revision ID: 6756efa39ada
Revises: 5d12a446f5c0
Create Date: 2024-10-15 17:47:44.108537

"""

from alembic import op
import sqlalchemy as sa

revision = "6756efa39ada"
down_revision = "5d12a446f5c0"
branch_labels = None
depends_on = None

"""
This script:
1. Adds UUID columns to chat_session and chat_message
2. Populates new columns with UUIDs
3. Updates foreign key relationships
4. Removes old integer ID columns

Note: Downgrade will assign new integer IDs, not restore original ones.
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    op.add_column(
        "chat_session",
        sa.Column(
            "new_id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )

    op.execute("UPDATE chat_session SET new_id = gen_random_uuid();")

    op.add_column(
        "chat_message",
        sa.Column("new_chat_session_id", sa.UUID(as_uuid=True), nullable=True),
    )

    op.execute(
        """
        UPDATE chat_message
        SET new_chat_session_id = cs.new_id
        FROM chat_session cs
        WHERE chat_message.chat_session_id = cs.id;
        """
    )

    op.drop_constraint(
        "chat_message_chat_session_id_fkey", "chat_message", type_="foreignkey"
    )

    op.drop_column("chat_message", "chat_session_id")
    op.alter_column(
        "chat_message", "new_chat_session_id", new_column_name="chat_session_id"
    )

    op.drop_constraint("chat_session_pkey", "chat_session", type_="primary")
    op.drop_column("chat_session", "id")
    op.alter_column("chat_session", "new_id", new_column_name="id")

    op.create_primary_key("chat_session_pkey", "chat_session", ["id"])

    op.create_foreign_key(
        "chat_message_chat_session_id_fkey",
        "chat_message",
        "chat_session",
        ["chat_session_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chat_message_chat_session_id_fkey", "chat_message", type_="foreignkey"
    )

    op.add_column(
        "chat_session",
        sa.Column("old_id", sa.Integer, autoincrement=True, nullable=True),
    )

    op.execute("CREATE SEQUENCE chat_session_old_id_seq OWNED BY chat_session.old_id;")
    op.execute(
        "ALTER TABLE chat_session ALTER COLUMN old_id SET DEFAULT nextval('chat_session_old_id_seq');"
    )

    op.execute(
        "UPDATE chat_session SET old_id = nextval('chat_session_old_id_seq') WHERE old_id IS NULL;"
    )

    op.alter_column("chat_session", "old_id", nullable=False)

    op.drop_constraint("chat_session_pkey", "chat_session", type_="primary")
    op.create_primary_key("chat_session_pkey", "chat_session", ["old_id"])

    op.add_column(
        "chat_message",
        sa.Column("old_chat_session_id", sa.Integer, nullable=True),
    )

    op.execute(
        """
        UPDATE chat_message
        SET old_chat_session_id = cs.old_id
        FROM chat_session cs
        WHERE chat_message.chat_session_id = cs.id;
        """
    )

    op.drop_column("chat_message", "chat_session_id")
    op.alter_column(
        "chat_message", "old_chat_session_id", new_column_name="chat_session_id"
    )

    op.create_foreign_key(
        "chat_message_chat_session_id_fkey",
        "chat_message",
        "chat_session",
        ["chat_session_id"],
        ["old_id"],
        ondelete="CASCADE",
    )

    op.drop_column("chat_session", "id")
    op.alter_column("chat_session", "old_id", new_column_name="id")

    op.alter_column(
        "chat_session",
        "id",
        type_=sa.Integer(),
        existing_type=sa.Integer(),
        existing_nullable=False,
        existing_server_default=False,
    )

    # Rename the sequence
    op.execute("ALTER SEQUENCE chat_session_old_id_seq RENAME TO chat_session_id_seq;")

    # Update the default value to use the renamed sequence
    op.alter_column(
        "chat_session",
        "id",
        server_default=sa.text("nextval('chat_session_id_seq'::regclass)"),
    )
