"""Port Config Store

Revision ID: 173cae5bba26
Revises: e50154680a5c
Create Date: 2024-03-19 15:30:44.425436

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "173cae5bba26"
down_revision = "e50154680a5c"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "key_value_store",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("key_value_store")
