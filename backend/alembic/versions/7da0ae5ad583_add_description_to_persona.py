"""Add description to persona

Revision ID: 7da0ae5ad583
Revises: e86866a9c78a
Create Date: 2023-11-27 00:16:19.959414

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "7da0ae5ad583"
down_revision = "e86866a9c78a"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("persona", sa.Column("description", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("persona", "description")
