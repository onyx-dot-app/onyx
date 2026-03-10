"""code interpreter server model

Revision ID: 7cb492013621
Revises: 0bb4558f35df
Create Date: 2026-02-22 18:54:54.007265

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7cb492013621"
down_revision = "0bb4558f35df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_interpreter_server",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "server_enabled", sa.Boolean, nullable=False, server_default=sa.true()
        ),
    )


def downgrade() -> None:
    op.drop_table("code_interpreter_server")
