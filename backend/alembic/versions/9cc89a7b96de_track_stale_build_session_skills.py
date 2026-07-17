"""track stale build session skills

Revision ID: 9cc89a7b96de
Revises: b1d060254b02
Create Date: 2026-07-16 19:10:35.958117

"""

from alembic import op
import sqlalchemy as sa

revision = "9cc89a7b96de"
down_revision = "b1d060254b02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "build_session",
        sa.Column(
            "skills_stale",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("build_session", "skills_stale")
