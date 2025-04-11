"""make document set description optional

Revision ID: 94dc3d0236f8
Revises: bf7a81109301
Create Date: 2024-12-11 11:26:10.616722

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "94dc3d0236f8"
down_revision = "bf7a81109301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make document_set.description column nullable
    op.alter_column(
        "document_set", "description", existing_type=sa.String(), nullable=True
    )


def downgrade() -> None:
    # Revert document_set.description column to non-nullable
    op.alter_column(
        "document_set", "description", existing_type=sa.String(), nullable=False
    )
