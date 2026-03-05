"""add_voice_provider_and_user_voice_prefs

Revision ID: 93a2e195e25c
Revises: 631fd2504136
Create Date: 2026-02-23 15:16:39.507304

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "93a2e195e25c"
down_revision = "631fd2504136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create voice_provider table
    op.create_table(
        "voice_provider",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), unique=True, nullable=False),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("api_key", sa.LargeBinary(), nullable=True),
        sa.Column("api_base", sa.String(), nullable=True),
        sa.Column("custom_config", postgresql.JSONB(), nullable=True),
        sa.Column("stt_model", sa.String(), nullable=True),
        sa.Column("tts_model", sa.String(), nullable=True),
        sa.Column("default_voice", sa.String(), nullable=True),
        sa.Column(
            "is_default_stt", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "is_default_tts", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # Add partial unique indexes to enforce only one default STT/TTS provider
    op.execute(
        """
        CREATE UNIQUE INDEX ix_voice_provider_one_default_stt
        ON voice_provider (is_default_stt)
        WHERE is_default_stt = true
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ix_voice_provider_one_default_tts
        ON voice_provider (is_default_tts)
        WHERE is_default_tts = true
        """
    )

    # Add voice preference columns to user table
    op.add_column(
        "user",
        sa.Column(
            "voice_auto_send",
            sa.Boolean(),
            default=False,
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "user",
        sa.Column(
            "voice_auto_playback",
            sa.Boolean(),
            default=False,
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "user",
        sa.Column(
            "voice_playback_speed",
            sa.Float(),
            default=1.0,
            nullable=False,
            server_default="1.0",
        ),
    )
    op.add_column(
        "user",
        sa.Column("preferred_voice", sa.String(), nullable=True),
    )


def downgrade() -> None:
    # Remove user voice preference columns
    op.drop_column("user", "preferred_voice")
    op.drop_column("user", "voice_playback_speed")
    op.drop_column("user", "voice_auto_playback")
    op.drop_column("user", "voice_auto_send")

    op.execute("DROP INDEX IF EXISTS ix_voice_provider_one_default_tts")
    op.execute("DROP INDEX IF EXISTS ix_voice_provider_one_default_stt")

    # Drop voice_provider table
    op.drop_table("voice_provider")
