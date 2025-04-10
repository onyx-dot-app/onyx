"""add new available tenant table

Revision ID: 3b45e0018bf1
Revises: ac842f85f932
Create Date: 2025-03-06 09:55:18.229910

"""

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision = "3b45e0018bf1"
down_revision = "ac842f85f932"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create new_available_tenant table
    op.create_table(
        "available_tenant",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("alembic_version", sa.String(), nullable=False),
        sa.Column("date_created", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
    )


def downgrade() -> None:
    # Drop new_available_tenant table
    op.drop_table("available_tenant")
