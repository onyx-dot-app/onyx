"""discord_bot

Revision ID: 38afd77fc912
Revises: 027381bce97c
Create Date: 2025-02-24 18:05:10.416216

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from onyx.db.models import EncryptedString

revision = "[will_be_auto_generated]"
down_revision = "027381bce97c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_bot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("discord_bot_token", EncryptedString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("discord_bot_token"),
    )

    op.create_table(
        "discord_channel_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("discord_bot_id", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column("channel_config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "enable_auto_filters", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.ForeignKeyConstraint(
            ["discord_bot_id"],
            ["discord_bot.id"],
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "discord_channel_config__standard_answer_category",
        sa.Column("discord_channel_config_id", sa.Integer(), nullable=False),
        sa.Column("standard_answer_category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["discord_channel_config_id"],
            ["discord_channel_config.id"],
        ),
        sa.ForeignKeyConstraint(
            ["standard_answer_category_id"],
            ["standard_answer_category.id"],
        ),
        sa.PrimaryKeyConstraint(
            "discord_channel_config_id", "standard_answer_category_id"
        ),
    )

    op.add_column(
        "chat_session", sa.Column("discord_thread_id", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_session", "discord_thread_id")
    op.drop_table("discord_channel_config__standard_answer_category")
    op.drop_table("discord_channel_config")
    op.drop_table("discord_bot")
