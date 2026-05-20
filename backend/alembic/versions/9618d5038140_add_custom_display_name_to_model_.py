"""add custom_display_name to model_configuration

Revision ID: 9618d5038140
Revises: e4ed20ddae7c
Create Date: 2026-05-19 08:35:16.817183

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9618d5038140"
down_revision = "e4ed20ddae7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configuration",
        sa.Column("custom_display_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_configuration", "custom_display_name")
