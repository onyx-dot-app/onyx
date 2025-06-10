"""add passthrough auth to tool

Revision ID: f1ca58b2f2ec
Revises: c7bf5721733e
Create Date: 2024-03-19

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1ca58b2f2ec"
down_revision: Union[str, None] = "c7bf5721733e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add passthrough_auth column to tool table with default value of False
    op.add_column(
        "tool",
        sa.Column(
            "passthrough_auth", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    # Remove passthrough_auth column from tool table
    op.drop_column("tool", "passthrough_auth")
