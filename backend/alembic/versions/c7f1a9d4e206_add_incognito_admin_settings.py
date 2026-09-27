"""add incognito availability, record mode, and the group flag

Revision ID: c7f1a9d4e206
Revises: 0ec213a5ffde
Create Date: 2026-08-12 09:40:00.000000

"""

import sqlalchemy as sa
from alembic import op

from onyx.db.enums import IncognitoRecordMode
from onyx.server.security.models import IncognitoAvailability

# revision identifiers, used by Alembic.
revision = "c7f1a9d4e206"
down_revision = "0ec213a5ffde"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both settings are nullable: NULL means the workspace never chose, which
    # reads as off and usage_only.
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
    op.add_column(
        "security_settings",
        sa.Column(
            "incognito_record_mode",
            sa.Enum(
                IncognitoRecordMode,
                native_enum=False,
                values_callable=lambda x: [e.value for e in x],
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "user_group",
        sa.Column(
            "incognito_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_group", "incognito_enabled")
    op.drop_column("security_settings", "incognito_record_mode")
    op.drop_column("security_settings", "incognito_availability")
