"""add content_hash to document

Revision ID: ea418a384b9d
Revises: e4ed20ddae7c
Create Date: 2026-05-18 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "ea418a384b9d"
down_revision = "e4ed20ddae7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column("content_hash", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document", "content_hash")
