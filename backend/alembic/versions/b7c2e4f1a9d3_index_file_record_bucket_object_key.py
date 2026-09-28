"""index file_record by bucket and object key

Revision ID: b7c2e4f1a9d3
Revises: ac05f4a21dbd
Create Date: 2026-09-25 16:05:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c2e4f1a9d3"
down_revision = "ac05f4a21dbd"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_index(
        "ix_file_record_bucket_name_object_key",
        "file_record",
        ["bucket_name", "object_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_file_record_bucket_name_object_key", table_name="file_record")
