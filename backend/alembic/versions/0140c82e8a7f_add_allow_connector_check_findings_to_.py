"""add allow_connector_check_findings to security_settings

Revision ID: 0140c82e8a7f
Revises: b6d920407aa6
Create Date: 2026-10-09 15:58:06.289734

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0140c82e8a7f"
down_revision = "b6d920407aa6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "security_settings",
        sa.Column("allow_connector_check_findings", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("security_settings", "allow_connector_check_findings")
