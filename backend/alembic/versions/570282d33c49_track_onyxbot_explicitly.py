"""Track Onyxbot Explicitly

Revision ID: 570282d33c49
Revises: 7547d982db8f
Create Date: 2024-05-04 17:49:28.568109

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "570282d33c49"
down_revision = "7547d982db8f"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "chat_session", sa.Column("danswerbot_flow", sa.Boolean(), nullable=True)
    )
    op.execute("UPDATE chat_session SET danswerbot_flow = one_shot")
    op.alter_column("chat_session", "danswerbot_flow", nullable=False)


def downgrade() -> None:
    op.drop_column("chat_session", "danswerbot_flow")
