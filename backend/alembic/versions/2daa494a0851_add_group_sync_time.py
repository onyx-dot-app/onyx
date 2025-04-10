"""add-group-sync-time

Revision ID: 2daa494a0851
Revises: c0fd6e4da83a
Create Date: 2024-11-11 10:57:22.991157

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2daa494a0851"
down_revision = "c0fd6e4da83a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "last_time_external_group_sync",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("connector_credential_pair", "last_time_external_group_sync")
