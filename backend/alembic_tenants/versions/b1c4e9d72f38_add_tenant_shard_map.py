"""add tenant shard map

Adds the tenant -> physical database ("shard") mapping used to route sessions when
tenants are spread across more than one Postgres database.

Deliberately not backfilled: a tenant with no row lives on the default shard, so this
table stays empty until tenants are actually migrated, and existing deployments are
unaffected.

Revision ID: b1c4e9d72f38
Revises: d4e7a92c1b38
Create Date: 2026-07-20

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b1c4e9d72f38"
down_revision = "d4e7a92c1b38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_shard",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("shard_name", sa.String(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
        schema="public",
    )
    # Migrator sweeps ask "which tenants are on shard X", so index the shard side too.
    op.create_index(
        "ix_tenant_shard_shard_name",
        "tenant_shard",
        ["shard_name"],
        schema="public",
    )

    # A pre-provisioned tenant schema physically exists on exactly one database and
    # cannot be handed out as living anywhere else. NULL means the default shard,
    # which is correct for every row that exists today.
    op.add_column(
        "available_tenant",
        sa.Column("shard_name", sa.String(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("available_tenant", "shard_name", schema="public")
    op.drop_index(
        "ix_tenant_shard_shard_name", table_name="tenant_shard", schema="public"
    )
    op.drop_table("tenant_shard", schema="public")
