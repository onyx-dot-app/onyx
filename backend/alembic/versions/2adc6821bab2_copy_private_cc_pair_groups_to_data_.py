"""copy private cc pair groups to data access

Revision ID: 2adc6821bab2
Revises: 38720c9e7f8f
Create Date: 2026-09-29 17:42:22.482530

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "2adc6821bab2"
down_revision = "38720c9e7f8f"
branch_labels = None
depends_on = None

# AccessType.PRIVATE as stored (native_enum=False stores the member name).
PRIVATE_ACCESS_TYPE = "PRIVATE"


def upgrade() -> None:
    """Data access for PRIVATE pairs now comes from user_group__cc_pair_data_access.
    Copy each current group of a PRIVATE pair into it, so every group keeps the
    documents it sees today."""
    cc_pair = sa.table(
        "connector_credential_pair",
        sa.column("id", sa.Integer),
        sa.column("access_type", sa.String),
    )
    manage = sa.table(
        "user_group__connector_credential_pair",
        sa.column("user_group_id", sa.Integer),
        sa.column("cc_pair_id", sa.Integer),
        sa.column("is_current", sa.Boolean),
    )
    data_access = sa.table(
        "user_group__cc_pair_data_access",
        sa.column("cc_pair_id", sa.Integer),
        sa.column("user_group_id", sa.Integer),
    )

    private_group_rows = (
        sa.select(manage.c.cc_pair_id, manage.c.user_group_id)
        .join(cc_pair, cc_pair.c.id == manage.c.cc_pair_id)
        .where(
            manage.c.is_current.is_(True),
            cc_pair.c.access_type == PRIVATE_ACCESS_TYPE,
        )
    )
    op.execute(
        postgresql.insert(data_access)
        .from_select(["cc_pair_id", "user_group_id"], private_group_rows)
        .on_conflict_do_nothing()
    )


def downgrade() -> None:
    # The copied rows cannot be told apart from rows written after the upgrade,
    # so they stay. The previous code does not read this table for PRIVATE
    # pairs, so the rows have no effect after a downgrade.
    pass
