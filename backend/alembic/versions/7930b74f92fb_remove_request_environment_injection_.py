"""remove request environment injection setting

Revision ID: 7930b74f92fb
Revises: 7a03b6e90c12
Create Date: 2026-09-14 15:22:38.000910

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7930b74f92fb"
down_revision = "7a03b6e90c12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("security_settings", "llm_custom_config_env_injection")


def downgrade() -> None:
    op.add_column(
        "security_settings",
        sa.Column("llm_custom_config_env_injection", sa.Boolean(), nullable=True),
    )
