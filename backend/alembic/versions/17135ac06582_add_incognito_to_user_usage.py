"""add incognito to user_usage

Revision ID: 17135ac06582
Revises: 3260759d6965
Create Date: 2026-08-10 12:30:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "17135ac06582"
down_revision = "3260759d6965"
branch_labels = None
depends_on = None

UNIQUE_INDEX = "uq_user_usage_dims"
BASE_DIMENSIONS = ["user_id", "window_start", "model", "flow", "provider"]


def upgrade() -> None:
    op.add_column(
        "user_usage",
        sa.Column(
            "incognito",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # incognito joins the rollup dimension tuple, so the upsert's unique index
    # must include it or two rows that differ only by mode would collide.
    op.drop_index(UNIQUE_INDEX, table_name="user_usage")
    op.create_index(
        UNIQUE_INDEX,
        "user_usage",
        [*BASE_DIMENSIONS, "incognito"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(UNIQUE_INDEX, table_name="user_usage")
    # Incognito rows only exist because of this revision, and without the
    # column they would collide with their ordinary counterparts on the
    # narrower index.
    op.execute(sa.text("DELETE FROM user_usage WHERE incognito"))
    op.drop_column("user_usage", "incognito")
    op.create_index(UNIQUE_INDEX, "user_usage", BASE_DIMENSIONS, unique=True)
