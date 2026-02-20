"""add default_app_mode to user

Revision ID: 114a638452db
Revises: feead2911109
Create Date: 2026-02-09 18:57:08.274640

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "114a638452db"
down_revision = "feead2911109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "default_app_mode",
            sa.String(),
            nullable=False,
            server_default="CHAT",
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "default_app_mode")
