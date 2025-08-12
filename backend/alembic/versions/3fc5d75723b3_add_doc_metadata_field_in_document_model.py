"""add_doc_metadata_field_in_document_model

Revision ID: 3fc5d75723b3
Revises: 2f95e36923e6
Create Date: 2025-07-28 18:45:37.985406

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "3fc5d75723b3"
down_revision = "2f95e36923e6"
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
