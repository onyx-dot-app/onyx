"""add audit settings to security_settings

Revision ID: 651681a57efa
Revises: 00a73eb4dccf
Create Date: 2026-11-27 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "651681a57efa"
down_revision = "00a73eb4dccf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "security_settings",
        sa.Column(
            "audit_event_categories", postgresql.ARRAY(sa.String()), nullable=True
        ),
    )
    op.add_column(
        "security_settings",
        sa.Column("audit_include_query_text", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("security_settings", "audit_include_query_text")
    op.drop_column("security_settings", "audit_event_categories")
