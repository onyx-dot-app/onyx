"""add file_size to file_record

Revision ID: a44c4ebac3d6
Revises: 3debc2b55899
Create Date: 2026-08-03 10:36:19.529472

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a44c4ebac3d6"
down_revision = "3debc2b55899"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_record",
        sa.Column("file_size", sa.BigInteger(), nullable=True),
    )
    # Backfill from the Postgres file-store content table where available.
    # Rows backed by external object storage stay NULL (size unknown).
    op.execute(
        """
        UPDATE file_record
        SET file_size = file_content.file_size
        FROM file_content
        WHERE file_content.file_id = file_record.file_id
        """
    )


def downgrade() -> None:
    op.drop_column("file_record", "file_size")
