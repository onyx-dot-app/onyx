"""Basic Document Metadata

Revision ID: ffc707a226b4
Revises: 30c1d5744104
Create Date: 2023-10-18 16:52:25.967592

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "ffc707a226b4"
down_revision = "30c1d5744104"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column("doc_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document",
        sa.Column("primary_owners", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "document",
        sa.Column("secondary_owners", postgresql.ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document", "secondary_owners")
    op.drop_column("document", "primary_owners")
    op.drop_column("document", "doc_updated_at")
