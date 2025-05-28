"""Restructure Document Indices

Revision ID: 8aabb57f3b49
Revises: 5e84129c8be3
Create Date: 2023-08-18 21:15:57.629515

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8aabb57f3b49"
down_revision = "5e84129c8be3"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_table("chunk")
    op.execute("DROP TYPE IF EXISTS documentstoretype")


def downgrade() -> None:
    op.create_table(
        "chunk",
        sa.Column("id", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column(
            "document_store_type",
            postgresql.ENUM("VECTOR", "KEYWORD", name="documentstoretype"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("document_id", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], name="chunk_document_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", "document_store_type", name="chunk_pkey"),
    )
