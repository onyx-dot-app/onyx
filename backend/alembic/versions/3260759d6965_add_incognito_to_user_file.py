"""add incognito columns to user_file

Revision ID: 3260759d6965
Revises: c7f1a9d4e206
Create Date: 2026-08-10 13:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3260759d6965"
down_revision = "c7f1a9d4e206"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_file",
        sa.Column(
            "incognito",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # No foreign key: the chat_session row is deleted at teardown and these
    # rows must outlive it long enough for the orphan sweep to find them.
    op.add_column(
        "user_file",
        sa.Column("incognito_session_id", sa.UUID(as_uuid=True), nullable=True),
    )
    # Partial index for the stale-incognito sweep, tiny since incognito rows
    # are short-lived.
    op.create_index(
        "ix_user_file_incognito_sweep",
        "user_file",
        ["incognito_session_id", "status", "last_accessed_at"],
        postgresql_where=sa.text("incognito"),
    )


def downgrade() -> None:
    op.drop_index("ix_user_file_incognito_sweep", table_name="user_file")
    op.drop_column("user_file", "incognito_session_id")
    op.drop_column("user_file", "incognito")
