"""Store Tool Details

Revision ID: 904451035c9b
Revises: 3b25685ff73c
Create Date: 2023-10-05 12:29:26.620000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "904451035c9b"
down_revision = "3b25685ff73c"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "persona",
        sa.Column("tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.drop_column("persona", "tools_text")


def downgrade() -> None:
    op.add_column(
        "persona",
        sa.Column("tools_text", sa.TEXT(), autoincrement=False, nullable=True),
    )
    op.drop_column("persona", "tools")
