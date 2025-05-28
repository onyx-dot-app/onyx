"""Add content type to UserFile

Revision ID: 5c448911b12f
Revises: 47a07e1a38f1
Create Date: 2025-04-25 16:59:48.182672

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "5c448911b12f"
down_revision = "47a07e1a38f1"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("user_file", sa.Column("content_type", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_file", "content_type")
