"""Add slack bot display type

Revision ID: fcd135795f21
Revises: 0a2b51deb0b8
Create Date: 2024-03-04 17:03:27.116284

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "fcd135795f21"
down_revision = "0a2b51deb0b8"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "slack_bot_config",
        sa.Column(
            "response_type",
            sa.Enum(
                "QUOTES",
                "CITATIONS",
                name="slackbotresponsetype",
                native_enum=False,
            ),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE slack_bot_config SET response_type = 'QUOTES' WHERE response_type IS NULL"
    )
    op.alter_column("slack_bot_config", "response_type", nullable=False)


def downgrade() -> None:
    op.drop_column("slack_bot_config", "response_type")
