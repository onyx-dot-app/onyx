"""add demo_data_enabled to build_session

Revision ID: 849b21c732f8
Revises: 81c22b1e2e78
Create Date: 2026-01-28 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "849b21c732f8"
down_revision = "81c22b1e2e78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "build_session",
        sa.Column(
            "demo_data_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("build_session", "demo_data_enabled")
