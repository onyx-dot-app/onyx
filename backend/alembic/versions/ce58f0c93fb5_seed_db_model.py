"""Seed db model

Revision ID: ce58f0c93fb5
Revises: 7cb492013621
Create Date: 2026-02-22 21:17:12.324708

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ce58f0c93fb5"
down_revision = "7cb492013621"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO code_interpreter_server (url, server_enabled) "
            "VALUES ('http://code-interpreter:8000', true)"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM code_interpreter_server "
            "WHERE url = 'http://code-interpreter:8000'"
        )
    )
