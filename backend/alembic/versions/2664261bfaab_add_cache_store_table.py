"""add cache_store table

Revision ID: 2664261bfaab
Revises: c0c937d5c9e5
Create Date: 2026-02-27 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2664261bfaab"
down_revision = "c0c937d5c9e5"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "cache_store",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.LargeBinary(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_cache_store_expires",
        "cache_store",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_cache_store_expires", table_name="cache_store")
    op.drop_table("cache_store")
