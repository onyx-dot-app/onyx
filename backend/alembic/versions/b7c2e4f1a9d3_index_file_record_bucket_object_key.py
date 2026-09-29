"""index file_record by bucket and object key

Revision ID: b7c2e4f1a9d3
Revises: 25053020dd5a
Create Date: 2026-09-25 16:05:00.000000

The legacy copy checks the file record of every object it copies, and without
an index that check scans the whole table. The build takes about two seconds
per million rows and holds writes to file_record for that long.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c2e4f1a9d3"
down_revision = "25053020dd5a"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_file_record_bucket_name_object_key"


def upgrade() -> None:
    op.create_index(INDEX_NAME, "file_record", ["bucket_name", "object_key"])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="file_record")
