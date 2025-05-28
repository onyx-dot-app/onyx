"""Remove Document IDs

Revision ID: d7111c1238cd
Revises: 465f78d9b7f9
Create Date: 2023-07-29 15:06:25.126169

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d7111c1238cd"
down_revision = "465f78d9b7f9"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_column("index_attempt", "document_ids")


def downgrade() -> None:
    op.add_column(
        "index_attempt",
        sa.Column(
            "document_ids",
            postgresql.ARRAY(sa.VARCHAR()),
            autoincrement=False,
            nullable=True,
        ),
    )
