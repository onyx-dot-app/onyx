from alembic import op
import sqlalchemy as sa
import datetime

# revision identifiers, used by Alembic.
revision = "25d86cbfce78"
down_revision = "c0aab6edb6dd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create user_folder table with additional 'display_priority' field
    op.create_table(
        "user_folder",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column(
            "parent_id", sa.Integer(), sa.ForeignKey("user_folder.id"), nullable=True
        ),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("display_priority", sa.Integer(), nullable=True, default=0),
        sa.Column("created_at", sa.DateTime(), default=datetime.datetime.utcnow),
    )

    # Migrate data from chat_folder to user_folder
    op.execute(
        """
        INSERT INTO user_folder (id, user_id, name, display_priority, created_at)
        SELECT id, user_id, name, display_priority, CURRENT_TIMESTAMP FROM chat_folder
        """
    )

    # Update chat_session table to reference user_folder instead of chat_folder
    op.drop_constraint(
        "chat_session_chat_folder_fk", "chat_session", type_="foreignkey"
    )
    op.alter_column(
        "chat_session",
        "folder_id",
        existing_type=sa.Integer(),
        nullable=True,
        existing_nullable=True,
        existing_server_default=None,
    )
    op.create_foreign_key(
        "fk_chat_session_folder_id_user_folder",
        "chat_session",
        "user_folder",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Drop the chat_folder table
    op.drop_table("chat_folder")

    # Create user_file table
    op.create_table(
        "user_file",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column(
            "parent_folder_id",
            sa.Integer(),
            sa.ForeignKey("user_folder.id"),
            nullable=True,
        ),
        sa.Column("file_type", sa.String(), nullable=True),
        sa.Column("file_id", sa.String(length=255), nullable=False),
        sa.Column("document_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            default=datetime.datetime.utcnow,
        ),
    )


def downgrade() -> None:
    # Recreate chat_folder table
    op.create_table(
        "chat_folder",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("display_priority", sa.Integer(), nullable=True, default=0),
    )

    # Migrate data back from user_folder to chat_folder
    op.execute(
        """
        INSERT INTO chat_folder (id, user_id, name, display_priority)
        SELECT id, user_id, name, display_priority FROM user_folder
        WHERE id IN (SELECT DISTINCT folder_id FROM chat_session WHERE folder_id IS NOT NULL)
        """
    )

    # Update chat_session table to reference chat_folder again
    op.drop_constraint(
        "fk_chat_session_folder_id_user_folder", "chat_session", type_="foreignkey"
    )
    op.alter_column(
        "chat_session",
        "folder_id",
        existing_type=sa.Integer(),
        nullable=True,
        existing_nullable=True,
        existing_server_default=None,
    )
    op.create_foreign_key(
        "chat_session_chat_folder_fk",
        "chat_session",
        "chat_folder",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Drop the user_file table
    op.drop_table("user_file")
    # Drop the user_folder table
    op.drop_table("user_folder")
