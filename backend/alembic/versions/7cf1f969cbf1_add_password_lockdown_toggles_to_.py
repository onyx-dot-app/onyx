"""add password lockdown toggles to security_settings

Revision ID: 7cf1f969cbf1
Revises: eec4fc85ef28
Create Date: 2026-07-09 17:37:14.166011

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7cf1f969cbf1"
down_revision = "eec4fc85ef28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable override columns. NULL falls back to the built-in default (enabled).
    op.add_column(
        "security_settings",
        sa.Column("password_signup_enabled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "security_settings",
        sa.Column("password_login_enabled", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("security_settings", "password_login_enabled")
    op.drop_column("security_settings", "password_signup_enabled")
