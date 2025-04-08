"""Add SlackBotConfig table

Revision ID: 7da543f5672f
Revises: febe9eaa0644
Create Date: 2023-09-24 16:34:17.526128

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "7da543f5672f"
down_revision = "febe9eaa0644"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "slack_bot_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column(
            "channel_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("slack_bot_config")
