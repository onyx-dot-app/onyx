"""add tenant schema snapshot

One row per shard and head revision: the SQL dump of that shard's template schema,
which apply_snapshot renders into a new tenant schema instead of replaying the chain.

Revision ID: 5e0d2a7c9f41
Revises: a754e4f72e60
Create Date: 2026-09-29

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "5e0d2a7c9f41"
down_revision = "a754e4f72e60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_schema_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shard_name", sa.String(), nullable=False),
        sa.Column("alembic_revision", sa.String(), nullable=False),
        sa.Column("dump", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shard_name", "alembic_revision"),
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("tenant_schema_snapshot", schema="public")
