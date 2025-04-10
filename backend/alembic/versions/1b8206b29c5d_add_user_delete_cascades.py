"""add_user_delete_cascades

Revision ID: 1b8206b29c5d
Revises: 35e6853a51d5
Create Date: 2024-09-18 11:48:59.418726

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "1b8206b29c5d"
down_revision = "35e6853a51d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("credential_user_id_fkey", "credential", type_="foreignkey")
    op.create_foreign_key(
        "credential_user_id_fkey",
        "credential",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("chat_session_user_id_fkey", "chat_session", type_="foreignkey")
    op.create_foreign_key(
        "chat_session_user_id_fkey",
        "chat_session",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("chat_folder_user_id_fkey", "chat_folder", type_="foreignkey")
    op.create_foreign_key(
        "chat_folder_user_id_fkey",
        "chat_folder",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("prompt_user_id_fkey", "prompt", type_="foreignkey")
    op.create_foreign_key(
        "prompt_user_id_fkey", "prompt", "user", ["user_id"], ["id"], ondelete="CASCADE"
    )

    op.drop_constraint("notification_user_id_fkey", "notification", type_="foreignkey")
    op.create_foreign_key(
        "notification_user_id_fkey",
        "notification",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("inputprompt_user_id_fkey", "inputprompt", type_="foreignkey")
    op.create_foreign_key(
        "inputprompt_user_id_fkey",
        "inputprompt",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("credential_user_id_fkey", "credential", type_="foreignkey")
    op.create_foreign_key(
        "credential_user_id_fkey", "credential", "user", ["user_id"], ["id"]
    )

    op.drop_constraint("chat_session_user_id_fkey", "chat_session", type_="foreignkey")
    op.create_foreign_key(
        "chat_session_user_id_fkey", "chat_session", "user", ["user_id"], ["id"]
    )

    op.drop_constraint("chat_folder_user_id_fkey", "chat_folder", type_="foreignkey")
    op.create_foreign_key(
        "chat_folder_user_id_fkey", "chat_folder", "user", ["user_id"], ["id"]
    )

    op.drop_constraint("prompt_user_id_fkey", "prompt", type_="foreignkey")
    op.create_foreign_key("prompt_user_id_fkey", "prompt", "user", ["user_id"], ["id"])

    op.drop_constraint("notification_user_id_fkey", "notification", type_="foreignkey")
    op.create_foreign_key(
        "notification_user_id_fkey", "notification", "user", ["user_id"], ["id"]
    )

    op.drop_constraint("inputprompt_user_id_fkey", "inputprompt", type_="foreignkey")
    op.create_foreign_key(
        "inputprompt_user_id_fkey", "inputprompt", "user", ["user_id"], ["id"]
    )
