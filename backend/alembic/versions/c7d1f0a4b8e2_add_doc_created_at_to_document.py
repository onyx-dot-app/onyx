"""add doc_created_at to document

Persist the source creation time on the document row so the indexing scan can
detect when a newly-supplied doc_created_at must be propagated to the index
(via a metadata-only update, without re-embedding).

Revision ID: c7d1f0a4b8e2
Revises: f6b0949ea33d
Create Date: 2026-07-07 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c7d1f0a4b8e2"
down_revision = "f6b0949ea33d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column("doc_created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document", "doc_created_at")
