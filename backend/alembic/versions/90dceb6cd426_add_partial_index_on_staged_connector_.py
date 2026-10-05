"""add partial index on staged connector files

Revision ID: 90dceb6cd426
Revises: bcf79eb7d0a8
Create Date: 2026-10-05 18:50:25.192848

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "90dceb6cd426"
down_revision = "bcf79eb7d0a8"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_file_record_staged_connector_files"


def upgrade() -> None:
    # Only staged connector uploads carry this key, so the index stays small
    # and the hourly staged-file cleanup does not scan the whole table.
    op.create_index(
        _INDEX_NAME,
        "file_record",
        ["created_at"],
        postgresql_where=sa.text("file_metadata ? 'staged_for_cc_pair_id'"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="file_record")
