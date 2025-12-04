"""Add icon_name field

Revision ID: ed9e44312505
Revises: 5e6f7a8b9c0d
Create Date: 2025-12-03 16:35:07.828393

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ed9e44312505"
down_revision = "5e6f7a8b9c0d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add icon_name column
    op.add_column("persona", sa.Column("icon_name", sa.String(), nullable=True))

    # Remove old icon columns
    op.drop_column("persona", "icon_shape")
    op.drop_column("persona", "icon_color")


def downgrade() -> None:
    # Re-add old icon columns
    op.add_column("persona", sa.Column("icon_color", sa.String(), nullable=True))
    op.add_column("persona", sa.Column("icon_shape", sa.Integer(), nullable=True))

    # Remove icon_name column
    op.drop_column("persona", "icon_name")
