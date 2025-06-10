"""persona_start_date

Revision ID: 797089dfb4d2
Revises: 55546a7967ee
Create Date: 2024-09-11 14:51:49.785835

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "797089dfb4d2"
down_revision = "55546a7967ee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "persona",
        sa.Column("search_start_date", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("persona", "search_start_date")
