"""Count Chat Tokens

Revision ID: 767f1c2a00eb
Revises: dba7f71618f5
Create Date: 2023-09-21 10:03:21.509899

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "767f1c2a00eb"
down_revision = "dba7f71618f5"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "chat_message", sa.Column("token_count", sa.Integer(), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("chat_message", "token_count")
