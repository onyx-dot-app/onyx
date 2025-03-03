"""new column user tenant mapping

Revision ID: ac842f85f932
Revises: 34e3630c7f32
Create Date: 2025-03-03 13:30:14.802874

"""
import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision = "ac842f85f932"
down_revision = "34e3630c7f32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add active column with default value of True
    # This will ensure all existing records are set to True
    op.add_column(
        "user_tenant_mapping",
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        schema="public",
    )

    op.execute(
        "CREATE UNIQUE INDEX uq_user_active_tenant_idx ON public.user_tenant_mapping (email) WHERE active = true"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.user_tenant_mapping DROP CONSTRAINT IF EXISTS uq_user_active_tenant_constraint"
    )

    # Remove the active column
    op.drop_column("user_tenant_mapping", "active", schema="public")
