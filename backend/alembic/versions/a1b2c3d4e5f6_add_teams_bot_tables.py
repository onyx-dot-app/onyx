"""add teams bot tables

Revision ID: a1b2c3d4e5f6
Revises: 6b3b4083c5aa
Create Date: 2026-03-02 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "6b3b4083c5aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teams_bot_config",
        sa.Column(
            "id",
            sa.String(),
            server_default=sa.text("'SINGLETON'"),
            nullable=False,
        ),
        sa.Column("app_id", sa.String(), nullable=False),
        sa.Column("app_secret", sa.LargeBinary(), nullable=False),
        sa.Column("azure_tenant_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 'SINGLETON'", name="ck_teams_bot_config_singleton"),
    )

    op.create_table(
        "teams_team_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("team_id", sa.String(), nullable=True),
        sa.Column("team_name", sa.String(length=256), nullable=True),
        sa.Column("registration_key", sa.String(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("default_persona_id", sa.Integer(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["default_persona_id"],
            ["persona.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id"),
        sa.UniqueConstraint("registration_key"),
    )

    op.create_table(
        "teams_channel_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("team_config_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("channel_name", sa.String(), nullable=False),
        sa.Column(
            "require_bot_mention",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("persona_override_id", sa.Integer(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["team_config_id"],
            ["teams_team_config.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["persona_override_id"],
            ["persona.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "team_config_id", "channel_id", name="uq_teams_channel_team_channel"
        ),
    )


def downgrade() -> None:
    op.drop_table("teams_channel_config")
    op.drop_table("teams_team_config")
    op.drop_table("teams_bot_config")
