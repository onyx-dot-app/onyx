"""Add name to api_key

Revision ID: 475fcefe8826
Revises: ecab2b3f1a3b
Create Date: 2024-04-11 11:05:18.414438

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "475fcefe8826"
down_revision = "ecab2b3f1a3b"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("api_key", sa.Column("name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_key", "name")
