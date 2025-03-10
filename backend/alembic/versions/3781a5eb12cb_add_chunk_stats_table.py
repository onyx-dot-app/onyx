"""add chunk stats table

Revision ID: 3781a5eb12cb
Revises: 3934b1bc7b62
Create Date: 2025-03-10 10:02:30.586666

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "3781a5eb12cb"
down_revision = "3934b1bc7b62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunk_stats",
        sa.Column("id", sa.String(), primary_key=True, index=True),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("document.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("chunk_in_doc_id", sa.Integer(), nullable=False),
        sa.Column("chunk_boost_components", postgresql.JSONB(), nullable=True),
        sa.Column(
            "last_modified",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
            server_default=sa.func.now(),
        ),
        sa.Column("last_synced", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.UniqueConstraint(
            "document_id", "chunk_in_doc_id", name="uq_chunk_stats_doc_chunk"
        ),
    )

    op.create_index(
        "ix_chunk_sync_status", "chunk_stats", ["last_modified", "last_synced"]
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_sync_status", table_name="chunk_stats")
    op.drop_table("chunk_stats")
