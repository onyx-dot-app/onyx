"""Add last synced and last modified to document table

Revision ID: 52a219fb5233
Revises: f7e58d357687
Create Date: 2024-08-28 17:40:46.077470

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func

# revision identifiers, used by Alembic.
revision = "52a219fb5233"
down_revision = "f7e58d357687"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # last modified represents the last time anything needing syncing to vespa changed
    # including row metadata and the document itself. This obviously does not include
    # the last_synced column.
    op.add_column(
        "document",
        sa.Column(
            "last_modified",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )

    # last synced represents the last time this document was synced to Vespa
    op.add_column(
        "document",
        sa.Column("last_synced", sa.DateTime(timezone=True), nullable=True),
    )

    # Set last_synced to the same value as last_modified for existing rows
    op.execute(
        """
        UPDATE document
        SET last_synced = last_modified
        """
    )

    op.create_index(
        op.f("ix_document_last_modified"),
        "document",
        ["last_modified"],
        unique=False,
    )

    op.create_index(
        op.f("ix_document_last_synced"),
        "document",
        ["last_synced"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_last_synced"), table_name="document")
    op.drop_index(op.f("ix_document_last_modified"), table_name="document")
    op.drop_column("document", "last_synced")
    op.drop_column("document", "last_modified")
