"""drop demo_data_enabled from build_session

Revision ID: 0df3c40e902a
Revises: b6d184cfdaf3
Create Date: 2026-05-12 21:56:44.263961

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0df3c40e902a"
down_revision = "b6d184cfdaf3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("build_session", "demo_data_enabled")


def downgrade() -> None:
    op.add_column(
        "build_session",
        sa.Column(
            "demo_data_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
