"""add_teams_bot_support

Revision ID: ac363e2a9363
Revises: ffc707a226b4
Create Date: 2024-03-21 10:00:00.000000

"""
from typing import cast
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "ac363e2a9363"
down_revision = "ffc707a226b4"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Create teams_bot table
    op.create_table(
        "teams_bot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_secret", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )

    # Create teams_channel_config table
    op.create_table(
        "teams_channel_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teams_bot_id", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column("channel_config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "enable_auto_filters", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(
            ["teams_bot_id"],
            ["teams_bot.id"],
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "teams_bot_id",
            "is_default",
            name="uq_teams_channel_config_teams_bot_id_default",
        ),
    )

    # Create teams_channel_config__standard_answer_category table
    op.create_table(
        "teams_channel_config__standard_answer_category",
        sa.Column("teams_channel_config_id", sa.Integer(), nullable=False),
        sa.Column("standard_answer_category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["teams_channel_config_id"],
            ["teams_channel_config.id"],
        ),
        sa.ForeignKeyConstraint(
            ["standard_answer_category_id"],
            ["standard_answer_category.id"],
        ),
        sa.PrimaryKeyConstraint(
            "teams_channel_config_id", "standard_answer_category_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("teams_channel_config__standard_answer_category")
    op.drop_table("teams_channel_config")
    op.drop_table("teams_bot") 