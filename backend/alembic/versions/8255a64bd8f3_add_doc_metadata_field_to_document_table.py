"""add_doc_metadata_field_to_document_table

Revision ID: 8255a64bd8f3
Revises: 0816326d83aa
Create Date: 2025-07-16 10:40:58.591430

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8255a64bd8f3"
down_revision = "0816326d83aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column(
            "doc_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("document", "doc_metadata")
