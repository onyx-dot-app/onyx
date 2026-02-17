"""add is_public to build_session

Revision ID: c7f2e1b4a9d3
Revises: 19c0ccb01687
Create Date: 2026-02-17 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c7f2e1b4a9d3"
down_revision = "19c0ccb01687"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "build_session",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("build_session", "is_public")
