"""remove multilingual_expansion from search_settings

Revision ID: a7c3e2b1d4f8
Revises: 856bcbe14d79
Create Date: 2026-04-16

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a7c3e2b1d4f8"
down_revision = "856bcbe14d79"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_column("search_settings", "multilingual_expansion")


def downgrade() -> None:
    op.add_column(
        "search_settings",
        sa.Column(
            "multilingual_expansion",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )
