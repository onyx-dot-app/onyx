"""Add support for custom tools

Revision ID: 48d14957fe80
Revises: b85f02ec1308
Create Date: 2024-06-09 14:58:19.946509

"""

from alembic import op
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "48d14957fe80"
down_revision = "b85f02ec1308"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column(
            "openapi_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "tool",
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
    )
    op.create_foreign_key("tool_user_fk", "tool", "user", ["user_id"], ["id"])

    op.create_table(
        "tool_call",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tool_id", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column(
            "tool_arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "tool_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "message_id", sa.Integer(), sa.ForeignKey("chat_message.id"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("tool_call")

    op.drop_constraint("tool_user_fk", "tool", type_="foreignkey")
    op.drop_column("tool", "user_id")
    op.drop_column("tool", "openapi_schema")
