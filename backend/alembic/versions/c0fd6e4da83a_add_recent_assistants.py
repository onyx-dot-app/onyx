"""add recent assistants

Revision ID: c0fd6e4da83a
Revises: b72ed7a5db0e
Create Date: 2024-11-03 17:28:54.916618

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c0fd6e4da83a"
down_revision = "b72ed7a5db0e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "recent_assistants", postgresql.JSONB(), server_default="[]", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "recent_assistants")
