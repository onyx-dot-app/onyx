"""add stub counts to index_attempt

`stubs_listed` counts the documents that the lister of the conversion stage
listed. `stubs_skipped` counts those it dropped because the stored document
has the same modified time and size.

Revision ID: 7a3c9e5b1d08
Revises: 5d1f8a6c2e47
Create Date: 2026-11-11 04:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7a3c9e5b1d08"
down_revision = "5d1f8a6c2e47"
branch_labels = None
depends_on = None

_COLUMNS = ("stubs_listed", "stubs_skipped")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column(
            "index_attempt",
            sa.Column(column, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for column in _COLUMNS:
        op.drop_column("index_attempt", column)
