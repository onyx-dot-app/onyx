"""move nextjs_port from sandbox to build_session

Revision ID: 76dd1eb17d31
Revises: 6db00b8237e5
Create Date: 2026-01-23 16:24:36.965851

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "76dd1eb17d31"
down_revision = "6db00b8237e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nextjs_port column to build_session (per-session port allocation)
    op.add_column(
        "build_session",
        sa.Column("nextjs_port", sa.Integer(), nullable=True),
    )
    # Drop nextjs_port column from sandbox (no longer needed at sandbox level)
    op.drop_column("sandbox", "nextjs_port")


def downgrade() -> None:
    # Add nextjs_port back to sandbox
    op.add_column(
        "sandbox",
        sa.Column("nextjs_port", sa.Integer(), nullable=True),
    )
    # Drop nextjs_port from build_session
    op.drop_column("build_session", "nextjs_port")
