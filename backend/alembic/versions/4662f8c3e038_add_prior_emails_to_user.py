"""add prior emails to user

Revision ID: 4662f8c3e038
Revises: 0d9c7b6a5e4f
Create Date: 2026-07-28 22:17:13.333593

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "4662f8c3e038"
down_revision = "b3f1c9a27d84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "prior_emails",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "prior_emails")
