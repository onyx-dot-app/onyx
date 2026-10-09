"""add role to user_group__connector_credential_pair

Revision ID: b3e7c1d9a4f2
Revises: 2adc6821bab2
Create Date: 2026-09-28 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3e7c1d9a4f2"
down_revision = "2adc6821bab2"
branch_labels = None
depends_on = None

# Stored by enum name (native_enum=False), as ConnectorManageRole is at this revision.
# Every existing manager row held today's full scoped-manager power, which is EDITOR.
EDITOR = "EDITOR"
ROLE_VALUES = ("EDITOR", "OPERATOR")
TABLE = "user_group__connector_credential_pair"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "role",
            sa.Enum(*ROLE_VALUES, name="connectormanagerole", native_enum=False),
            nullable=False,
            server_default=EDITOR,
        ),
    )
    # The default only backfills existing rows; every writer states its role.
    op.alter_column(TABLE, "role", server_default=None)


def downgrade() -> None:
    op.drop_column(TABLE, "role")
