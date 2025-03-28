"""Create table user_slack_persona

Revision ID: 792d1af3dc44
Revises: 3a7802814195
Create Date: 2025-01-24 04:26:02.844951

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "792d1af3dc44"
down_revision = "3a7802814195"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_slack_persona",
        sa.Column("sender_id", sa.String(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.PrimaryKeyConstraint("sender_id"),
    )


def downgrade() -> None:
    op.drop_table("user_slack_persona")
