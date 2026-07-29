"""add user tenant mapping oauth account table

Revision ID: 8f3d2c7b91ae
Revises: b1c4e9d72f38
Create Date: 2026-07-29 20:14:03.117204

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "8f3d2c7b91ae"
down_revision = "b1c4e9d72f38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_tenant_mapping_oauth_account",
        sa.Column("oauth_name", sa.String(length=100), nullable=False),
        sa.Column("account_id", sa.String(length=320), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["email", "tenant_id"],
            [
                "public.user_tenant_mapping.email",
                "public.user_tenant_mapping.tenant_id",
            ],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("oauth_name", "account_id"),
        schema="public",
    )
    op.create_index(
        "ix_user_tenant_mapping_oauth_account_mapping",
        "user_tenant_mapping_oauth_account",
        ["email", "tenant_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_tenant_mapping_oauth_account_mapping",
        table_name="user_tenant_mapping_oauth_account",
        schema="public",
    )
    op.drop_table("user_tenant_mapping_oauth_account", schema="public")
