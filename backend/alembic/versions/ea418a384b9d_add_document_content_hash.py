"""add content_hash to document

Revision ID: ea418a384b9d
Revises: 9618d5038140
Create Date: 2026-05-18 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "ea418a384b9d"
down_revision = "9618d5038140"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column("content_hash", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document", "content_hash")
