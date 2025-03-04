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

    # Drop the original unique constraint on email only
    op.drop_constraint("uq_email", "user_tenant_mapping", schema="public")

    # Drop the original unique constraint on email and tenant_id
    op.drop_constraint("uq_user_tenant", "user_tenant_mapping", schema="public")

    # Create a new unique constraint for email-tenant combination
    # This ensures a user can't have multiple records in the same tenant
    op.create_unique_constraint(
        "uq_user_tenant", "user_tenant_mapping", ["email", "tenant_id"], schema="public"
    )

    # Create a unique index for active=true records
    # This ensures a user can only be active in one tenant at a time
    op.execute(
        "CREATE UNIQUE INDEX uq_user_active_email_idx ON public.user_tenant_mapping (email) WHERE active = true"
    )


def downgrade() -> None:
    # Drop the unique index for active=true records
    op.execute("DROP INDEX IF EXISTS uq_user_active_email_idx")

    # Drop the unique constraint for email-tenant combination
    op.drop_constraint("uq_user_tenant", "user_tenant_mapping", schema="public")

    # Recreate the original unique constraints
    op.create_unique_constraint(
        "uq_user_tenant", "user_tenant_mapping", ["email", "tenant_id"], schema="public"
    )
    op.create_unique_constraint(
        "uq_email", "user_tenant_mapping", ["email"], schema="public"
    )

    # Remove the active column
    op.drop_column("user_tenant_mapping", "active", schema="public")
