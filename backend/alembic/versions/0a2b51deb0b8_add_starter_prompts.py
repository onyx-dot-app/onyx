"""Add starter prompts

Revision ID: 0a2b51deb0b8
Revises: 5f4b8568a221
Create Date: 2024-03-02 23:23:49.960309

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0a2b51deb0b8"
down_revision = "5f4b8568a221"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "persona",
        sa.Column(
            "starter_messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("persona", "starter_messages")
