"""added is_internet to DBDoc

Revision ID: 4505fd7302e1
Revises: c18cdf4b497e
Create Date: 2024-06-18 20:46:09.095034

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4505fd7302e1"
down_revision = "c18cdf4b497e"


def upgrade() -> None:
    op.add_column("search_doc", sa.Column("is_internet", sa.Boolean(), nullable=True))
    op.add_column("tool", sa.Column("display_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tool", "display_name")
    op.drop_column("search_doc", "is_internet")
