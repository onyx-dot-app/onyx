"""lowercase multi-tenant user auth

Revision ID: 34e3630c7f32
Revises: a4f6ee863c47
Create Date: 2025-02-26 15:03:01.211894

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "34e3630c7f32"
down_revision = "a4f6ee863c47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Convert all existing rows to lowercase
    op.execute(
        """
        UPDATE user_tenant_mapping
        SET email = LOWER(email)
        """
    )
    # 2) Add a check constraint so that emails cannot be written in uppercase
    op.create_check_constraint(
        "ensure_lowercase_email",
        "user_tenant_mapping",
        "email = LOWER(email)",
        schema="public",
    )


def downgrade() -> None:
    # Drop the check constraint
    op.drop_constraint(
        "ensure_lowercase_email",
        "user_tenant_mapping",
        schema="public",
        type_="check",
    )
