"""add nextjs_port to sandbox

Revision ID: 7cd906f37fc6
Revises: 26b589bf8be7
Create Date: 2026-01-20

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7cd906f37fc6"
down_revision: Union[str, None] = "26b589bf8be7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sandbox", sa.Column("nextjs_port", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("sandbox", "nextjs_port")
