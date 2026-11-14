"""add mentions to chat_message and chat_input

A question records what the user tagged in it with `@`, as its turn resolved
it. A custom skill keeps the plugin version the user ran when the question was
accepted. A pending input keeps the requested mentions until its turn accepts
it.

Revision ID: c4e8a1f2b7d9
Revises: 414dfccc5e24
Create Date: 2026-11-13 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c4e8a1f2b7d9"
down_revision = "414dfccc5e24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A constant default adds each column without rewriting its table.
    for table in ("chat_message", "chat_input"):
        op.add_column(
            table,
            sa.Column(
                "mentions",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.drop_column("chat_input", "mentions")
    op.drop_column("chat_message", "mentions")
