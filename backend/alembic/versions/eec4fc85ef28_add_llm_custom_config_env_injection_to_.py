"""add llm_custom_config_env_injection to security_settings

Revision ID: eec4fc85ef28
Revises: 9cc89a7b96de
Create Date: 2026-07-19 19:14:17.334151

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "eec4fc85ef28"
down_revision = "9cc89a7b96de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "security_settings",
        sa.Column("llm_custom_config_env_injection", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("security_settings", "llm_custom_config_env_injection")
