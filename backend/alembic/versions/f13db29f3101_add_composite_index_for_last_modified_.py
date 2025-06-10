"""Add composite index for last_modified and last_synced to document

Revision ID: f13db29f3101
Revises: b388730a2899
Create Date: 2025-02-18 22:48:11.511389

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f13db29f3101"
down_revision = "acaab4ef4507"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_document_sync_status",
        "document",
        ["last_modified", "last_synced"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_sync_status", table_name="document")
