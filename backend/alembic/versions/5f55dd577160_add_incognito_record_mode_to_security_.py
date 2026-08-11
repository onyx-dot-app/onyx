"""add incognito_record_mode to security_settings

Revision ID: 5f55dd577160
Revises: 55a631a86948
Create Date: 2026-08-11 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

from onyx.db.enums import IncognitoRecordMode


# revision identifiers, used by Alembic.
revision = "5f55dd577160"
down_revision = "55a631a86948"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_column("security_settings", "incognito_record_mode")
