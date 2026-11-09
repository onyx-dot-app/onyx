"""add source_mime_type and source_size_bytes to document

The file type and size the source reports, so the connector page can break a
cc-pair's indexed documents down by type. Existing rows stay null until a
re-index fills them.

Revision ID: b20bded0b4f3
Revises: f9f6abda4011
Create Date: 2026-11-04 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b20bded0b4f3"
down_revision = "f9f6abda4011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column("source_mime_type", sa.String(), nullable=True),
    )
    op.add_column(
        "document",
        sa.Column("source_size_bytes", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document", "source_size_bytes")
    op.drop_column("document", "source_mime_type")
