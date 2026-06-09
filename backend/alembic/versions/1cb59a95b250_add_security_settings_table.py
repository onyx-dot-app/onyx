"""add security_settings table

Replaces the per-tenant ``onyx_security_settings`` JSONB blob in
``key_value_store`` with a dedicated, typed ``security_settings`` table.

The table holds a single row per tenant schema (enforced by a boolean
primary key pinned to ``true`` via CHECK). Every column is an *override*:
``NULL`` means "fall back to the env-derived default", mirroring the
``SecuritySettingsOverrides`` storage shape (absent field == env default).

Revision ID: 1cb59a95b250
Revises: 99ecd56cb2ce
Create Date: 2026-06-09 17:36:09.181328

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "1cb59a95b250"
down_revision = "99ecd56cb2ce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_settings",
        # Singleton row: pinned to true so a second INSERT collides on the PK.
        sa.Column(
            "id",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("user_directory_admin_only", sa.Boolean(), nullable=True),
        sa.Column("track_external_idp_expiry", sa.Boolean(), nullable=True),
        sa.Column("mask_credential_prefix", sa.Boolean(), nullable=True),
        sa.Column(
            "valid_email_domains",
            postgresql.ARRAY(sa.String()),
            nullable=True,
        ),
        sa.Column("password_min_length", sa.Integer(), nullable=True),
        sa.Column("password_max_length", sa.Integer(), nullable=True),
        sa.Column("password_require_uppercase", sa.Boolean(), nullable=True),
        sa.Column("password_require_lowercase", sa.Boolean(), nullable=True),
        sa.Column("password_require_digit", sa.Boolean(), nullable=True),
        sa.Column("password_require_special_char", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = true", name="ck_security_settings_singleton"),
    )


def downgrade() -> None:
    op.drop_table("security_settings")
