"""add stub batch counters to index_attempt

Counters for the conversion stage: stub batches stored by the lister, sent
to conversion, and converted into document batches. It also merges the two
heads on main (fdaeeca238a1 and c7bf5721733e).

Revision ID: 3b7e2c9d41a6
Revises: fdaeeca238a1, c7bf5721733e
Create Date: 2026-11-10 16:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3b7e2c9d41a6"
down_revision = ("fdaeeca238a1", "c7bf5721733e")
branch_labels = None
depends_on = None

_COLUMNS = (
    "stub_batches_stored",
    "stub_batches_sent",
    "stub_batches_converted",
)


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column(
            "index_attempt",
            sa.Column(column, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for column in _COLUMNS:
        op.drop_column("index_attempt", column)
