"""drop deferrable foreign keys

Deferred checks wait until commit. Every pending revision runs in one
transaction, so a later ALTER TABLE on a table with waiting checks fails with
"pending trigger events". Application code keeps these pointers valid.

Revision ID: 414dfccc5e24
Revises: 7a3d5c1e9b42
Create Date: 2026-11-13 12:29:36.423681

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "414dfccc5e24"
down_revision = "7a3d5c1e9b42"
branch_labels = None
depends_on = None

_PLUGIN_VERSION_POINTERS = (
    ("fk_plugin_current_version", "current_version_id"),
    ("fk_plugin_published_version", "published_version_id"),
    ("fk_plugin_pending_version", "pending_version_id"),
)


def upgrade() -> None:
    for name, _ in _PLUGIN_VERSION_POINTERS:
        op.drop_constraint(name, "plugin", type_="foreignkey")
    op.drop_constraint("fk_chat_message_invocation", "chat_message", type_="foreignkey")


def downgrade() -> None:
    for name, column in _PLUGIN_VERSION_POINTERS:
        op.create_foreign_key(
            name,
            "plugin",
            "plugin_version",
            [column, "id"],
            ["id", "plugin_id"],
            deferrable=True,
            initially="DEFERRED",
        )
    op.create_foreign_key(
        "fk_chat_message_invocation",
        "chat_message",
        "tool_call",
        ["invoking_tool_call_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
        postgresql_not_valid=True,
    )
