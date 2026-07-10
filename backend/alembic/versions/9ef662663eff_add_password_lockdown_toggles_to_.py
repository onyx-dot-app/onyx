"""add password lockdown toggles to security_settings

Revision ID: 9ef662663eff
Revises: f6b0949ea33d
Create Date: 2026-07-09 17:37:14.166011

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9ef662663eff"
down_revision = "f6b0949ea33d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable override columns. NULL falls back to the env default.
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
