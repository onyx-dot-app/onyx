"""add allow_connector_group_restrictions to security_settings

Revision ID: df879de08494
Revises: ad99acb9be41
Create Date: 2026-09-23 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "df879de08494"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "security_settings",
        sa.Column("allow_connector_group_restrictions", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("security_settings", "allow_connector_group_restrictions")
