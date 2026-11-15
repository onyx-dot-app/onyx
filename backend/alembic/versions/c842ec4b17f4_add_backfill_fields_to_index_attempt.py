"""add backfill fields to index_attempt

Revision ID: c842ec4b17f4
Revises: 50bbc151ad39
Create Date: 2026-10-05 16:11:19.802493

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c842ec4b17f4"
down_revision = "50bbc151ad39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "index_attempt",
        sa.Column(
            "is_backfill",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "connector_config_override",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("index_attempt", "connector_config_override")
    op.drop_column("index_attempt", "is_backfill")
