"""Store the inputs that each model generation accepted.

Revision ID: 01300220f1e1
Revises: 43484c519a86
Create Date: 2026-11-11 18:01:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "01300220f1e1"
down_revision = "43484c519a86"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_response_item",
        sa.Column(
            "inputs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_response_item", "inputs")
