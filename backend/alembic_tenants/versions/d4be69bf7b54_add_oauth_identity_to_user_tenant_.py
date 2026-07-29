"""add oauth identity to user tenant mapping

Revision ID: d4be69bf7b54
Revises: b1c4e9d72f38
Create Date: 2026-07-28 21:50:27.740918

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d4be69bf7b54"
down_revision = "b1c4e9d72f38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widths mirror the `oauth_account` columns these values are copied from.
    op.add_column(
        "user_tenant_mapping",
        sa.Column("oauth_name", sa.String(length=100), nullable=True),
        schema="public",
    )
    op.add_column(
        "user_tenant_mapping",
        sa.Column("account_id", sa.String(length=320), nullable=True),
        schema="public",
    )

    # Not unique: one identity holds a row per tenant it belongs to.
    # Partial so it covers only stamped rows.
    op.create_index(
        "ix_user_tenant_mapping_oauth_identity",
        "user_tenant_mapping",
        ["oauth_name", "account_id"],
        schema="public",
        postgresql_where=sa.text("oauth_name IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_tenant_mapping_oauth_identity",
        table_name="user_tenant_mapping",
        schema="public",
    )
    op.drop_column("user_tenant_mapping", "account_id", schema="public")
    op.drop_column("user_tenant_mapping", "oauth_name", schema="public")
