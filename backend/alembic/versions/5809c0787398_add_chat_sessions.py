"""Add Chat Sessions

Revision ID: 5809c0787398
Revises: d929f0c1c6af
Create Date: 2023-09-04 15:29:44.002164

"""

import fastapi_users_db_sqlalchemy
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5809c0787398"
down_revision = "d929f0c1c6af"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "chat_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column(
            "time_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chat_message",
        sa.Column("chat_session_id", sa.Integer(), nullable=False),
        sa.Column("message_number", sa.Integer(), nullable=False),
        sa.Column("edit_number", sa.Integer(), nullable=False),
        sa.Column("parent_edit_number", sa.Integer(), nullable=True),
        sa.Column("latest", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "message_type",
            sa.Enum(
                "SYSTEM",
                "USER",
                "ASSISTANT",
                "DANSWER",
                name="messagetype",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "time_sent",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"],
            ["chat_session.id"],
        ),
        sa.PrimaryKeyConstraint("chat_session_id", "message_number", "edit_number"),
    )


def downgrade() -> None:
    op.drop_table("chat_message")
    op.drop_table("chat_session")
