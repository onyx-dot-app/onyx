"""Chat Folders

Revision ID: 7547d982db8f
Revises: ef7da92f7213
Create Date: 2024-05-02 15:18:56.573347

"""

from alembic import op
import sqlalchemy as sa
import fastapi_users_db_sqlalchemy

# revision identifiers, used by Alembic.
revision = "7547d982db8f"
down_revision = "ef7da92f7213"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "chat_folder",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("display_priority", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("chat_session", sa.Column("folder_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "chat_session_chat_folder_fk",
        "chat_session",
        "chat_folder",
        ["folder_id"],
        ["id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "chat_session" in inspector.get_table_names():
        chat_session_fks = {
            fk.get("name") for fk in inspector.get_foreign_keys("chat_session")
        }
        if "chat_session_chat_folder_fk" in chat_session_fks:
            op.drop_constraint(
                "chat_session_chat_folder_fk", "chat_session", type_="foreignkey"
            )

        chat_session_columns = {
            col["name"] for col in inspector.get_columns("chat_session")
        }
        if "folder_id" in chat_session_columns:
            op.drop_column("chat_session", "folder_id")

    if "chat_folder" in inspector.get_table_names():
        op.drop_table("chat_folder")
