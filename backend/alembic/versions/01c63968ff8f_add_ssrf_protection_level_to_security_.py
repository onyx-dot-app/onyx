"""add ssrf_protection_level to security_settings

Revision ID: 01c63968ff8f
Revises: 1cb59a95b250
Create Date: 2026-06-09 17:11:49.835715

"""

from alembic import op
import sqlalchemy as sa

from onyx.server.security.models import SSRFProtectionLevel


# revision identifiers, used by Alembic.
revision = "01c63968ff8f"
down_revision = "1cb59a95b250"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "security_settings",
        sa.Column(
            "ssrf_protection_level",
            sa.Enum(
                SSRFProtectionLevel,
                native_enum=False,
                values_callable=lambda x: [e.value for e in x],
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("security_settings", "ssrf_protection_level")
