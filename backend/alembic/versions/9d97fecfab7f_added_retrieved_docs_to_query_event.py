"""Added retrieved docs to query event

Revision ID: 9d97fecfab7f
Revises: ffc707a226b4
Create Date: 2023-10-20 12:22:31.930449

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9d97fecfab7f"
down_revision = "ffc707a226b4"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "query_event",
        sa.Column(
            "retrieved_document_ids",
            postgresql.ARRAY(sa.String()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("query_event", "retrieved_document_ids")
