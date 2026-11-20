"""move user preferences to their own table

`user` keeps identity, access and profile fields. The settings a user picks
for themselves move to `user_preferences`, one row per user. The `user`
column `user_preferences` (free-text instructions) becomes
`user_preferences.instructions`.

Revision ID: d5f9b2a4c3e8
Revises: 170d8004af5b
Create Date: 2026-11-20 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "d5f9b2a4c3e8"
down_revision = "170d8004af5b"
branch_labels = None
depends_on = None


def _preference_columns(instructions_name: str) -> list[sa.Column]:
    """The preference columns with the types, nullability and server defaults
    that they have on `user`."""
    return [
        sa.Column("default_model", sa.Text(), nullable=True),
        sa.Column("temperature_override_enabled", sa.Boolean(), nullable=True),
        sa.Column("temperature_default", sa.Float(), nullable=True),
        sa.Column("reasoning_effort_default", sa.String(length=6), nullable=True),
        sa.Column("auto_scroll", sa.Boolean(), nullable=True),
        sa.Column(
            "shortcut_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("theme_preference", sa.String(length=6), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("chat_background", sa.String(), nullable=True),
        sa.Column(
            "default_app_mode",
            sa.String(),
            nullable=False,
            server_default="CHAT",
        ),
        sa.Column(
            "use_memories",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "enable_memory_tool",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(instructions_name, sa.Text(), nullable=True),
        sa.Column("chosen_assistants", postgresql.JSONB(), nullable=True),
        sa.Column(
            "visible_assistants",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "hidden_assistants",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "paste_as_tile",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "interrupt_on_send",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "voice_auto_send",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "voice_auto_playback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "voice_playback_speed",
            sa.Float(),
            nullable=False,
            server_default="1",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        *_preference_columns("instructions"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # Every existing user gets a row with their current values.
    op.execute(
        """
        INSERT INTO user_preferences (
            user_id,
            default_model,
            temperature_override_enabled,
            temperature_default,
            reasoning_effort_default,
            auto_scroll,
            shortcut_enabled,
            theme_preference,
            language,
            chat_background,
            default_app_mode,
            use_memories,
            enable_memory_tool,
            instructions,
            chosen_assistants,
            visible_assistants,
            hidden_assistants,
            paste_as_tile,
            interrupt_on_send,
            voice_auto_send,
            voice_auto_playback,
            voice_playback_speed
        )
        SELECT
            id,
            default_model,
            temperature_override_enabled,
            temperature_default,
            reasoning_effort_default,
            auto_scroll,
            shortcut_enabled,
            theme_preference,
            language,
            chat_background,
            default_app_mode,
            use_memories,
            enable_memory_tool,
            user_preferences,
            chosen_assistants,
            visible_assistants,
            hidden_assistants,
            paste_as_tile,
            interrupt_on_send,
            voice_auto_send,
            voice_auto_playback,
            voice_playback_speed
        FROM "user"
        """
    )

    for column in _preference_columns("user_preferences"):
        op.drop_column("user", column.name)


def downgrade() -> None:
    # A user without a `user_preferences` row gets the server defaults.
    for column in _preference_columns("user_preferences"):
        op.add_column("user", column)

    op.execute(
        """
        UPDATE "user" SET
            default_model = p.default_model,
            temperature_override_enabled = p.temperature_override_enabled,
            temperature_default = p.temperature_default,
            reasoning_effort_default = p.reasoning_effort_default,
            auto_scroll = p.auto_scroll,
            shortcut_enabled = p.shortcut_enabled,
            theme_preference = p.theme_preference,
            language = p.language,
            chat_background = p.chat_background,
            default_app_mode = p.default_app_mode,
            use_memories = p.use_memories,
            enable_memory_tool = p.enable_memory_tool,
            user_preferences = p.instructions,
            chosen_assistants = p.chosen_assistants,
            visible_assistants = p.visible_assistants,
            hidden_assistants = p.hidden_assistants,
            paste_as_tile = p.paste_as_tile,
            interrupt_on_send = p.interrupt_on_send,
            voice_auto_send = p.voice_auto_send,
            voice_auto_playback = p.voice_auto_playback,
            voice_playback_speed = p.voice_playback_speed
        FROM user_preferences AS p
        WHERE "user".id = p.user_id
        """
    )

    op.drop_table("user_preferences")
