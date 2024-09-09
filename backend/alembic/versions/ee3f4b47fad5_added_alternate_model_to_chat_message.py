"""Added alternate model to chat message

Revision ID: ee3f4b47fad5
Revises: 2d2304e27d8c
Create Date: 2024-08-12 00:11:50.915845

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ee3f4b47fad5"
down_revision = "2d2304e27d8c"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("overridden_model", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "overridden_model")
