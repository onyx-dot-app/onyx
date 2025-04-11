"""add composite index for index attempt time updated

Revision ID: 369644546676
Revises: 2955778aa44c
Create Date: 2025-01-08 15:38:17.224380

"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "369644546676"
down_revision = "2955778aa44c"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_index(
        "ix_index_attempt_ccpair_search_settings_time_updated",
        "index_attempt",
        [
            "connector_credential_pair_id",
            "search_settings_id",
            text("time_updated DESC"),
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_index_attempt_ccpair_search_settings_time_updated",
        table_name="index_attempt",
    )
