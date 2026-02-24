"""code interpreter seed

Revision ID: 07b98176f1de
Revises: 7cb492013621
Create Date: 2026-02-23 15:55:07.606784

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "07b98176f1de"
down_revision = "7cb492013621"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Seed the single instance of code_interpreter_server
    # NOTE: There should only exist at most and at minimum 1 code_interpreter_server row
    op.execute(
        sa.text("INSERT INTO code_interpreter_server (server_enabled) VALUES (true)")
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM code_interpreter_server"))
