"""add Teams bot configuration

Revision ID: eee92f463d0f
Revises: ad99acb9be41
Create Date: 2026-09-19 18:30:11.251618

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "eee92f463d0f"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teams_bot_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("app_id", sa.UUID(), nullable=False),
        sa.Column("directory_id", sa.UUID(), nullable=False),
        sa.Column("client_secret", sa.LargeBinary(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_teams_bot_singleton"),
        sa.ForeignKeyConstraint(["persona_id"], ["persona.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("teams_bot_config")
