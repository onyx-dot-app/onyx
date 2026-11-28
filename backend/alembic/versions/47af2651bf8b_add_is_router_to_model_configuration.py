"""add is_router to model_configuration

Revision ID: 47af2651bf8b
Revises: 1b26b1dfdc54
Create Date: 2026-10-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "47af2651bf8b"
down_revision = "078171a436f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configuration",
        sa.Column(
            "is_router",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("model_configuration", "is_router")
