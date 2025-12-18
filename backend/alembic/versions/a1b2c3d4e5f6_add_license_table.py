"""add license table

Revision ID: a1b2c3d4e5f6
Revises: a01bf2971c5d
Create Date: 2025-12-04 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "a01bf2971c5d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "license",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("license_data", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Singleton pattern - only ever one row in this table
    op.create_index(
        "idx_license_singleton",
        "license",
        [sa.text("(true)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_license_singleton", table_name="license")
    op.drop_table("license")
