"""add tenant sso domain routing

Revision ID: a754e4f72e60
Revises: 8f3d2c7b91ae
Create Date: 2026-08-06 17:01:52.971034

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a754e4f72e60"
down_revision = "8f3d2c7b91ae"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_sso_domain",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "domain"),
        schema="public",
    )
    # Only one workspace may hold a domain as verified. Pending claims may overlap.
    op.create_index(
        "uq_tenant_sso_domain_verified",
        "tenant_sso_domain",
        ["domain"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("verified_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_tenant_sso_domain_verified",
        table_name="tenant_sso_domain",
        schema="public",
    )
    op.drop_table("tenant_sso_domain", schema="public")
