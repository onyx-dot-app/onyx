"""add incognito_availability to security_settings

Revision ID: 55a631a86948
Revises: 1d32626a7bbb
Create Date: 2026-08-10 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

from onyx.server.security.models import IncognitoAvailability


# revision identifiers, used by Alembic.
revision = "55a631a86948"
down_revision = "1d32626a7bbb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "security_settings",
        sa.Column(
            "incognito_availability",
            sa.Enum(
                IncognitoAvailability,
                native_enum=False,
                values_callable=lambda x: [e.value for e in x],
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("security_settings", "incognito_availability")
