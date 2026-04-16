"""Add file_id to documents

Revision ID: 91d150c361f6
Revises: d129f37b3d87
Create Date: 2026-04-16 15:43:30.314823

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "91d150c361f6"
down_revision = "d129f37b3d87"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column("file_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document", "file_id")
