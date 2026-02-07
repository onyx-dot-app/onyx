"""add_file_content

Revision ID: d56ffa94ca32
Revises: 01f8e6d95a33
Create Date: 2026-02-06 15:29:34.192960

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d56ffa94ca32"
down_revision = "01f8e6d95a33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_content",
        sa.Column(
            "file_id",
            sa.String(),
            sa.ForeignKey("file_record.file_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("lobj_oid", sa.BigInteger(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("file_content")
