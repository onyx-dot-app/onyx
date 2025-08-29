"""Adding assistant-specific user preferences

Revision ID: b329d00a9ea6
Revises: f9b8c7d6e5a4
Create Date: 2025-08-26 23:14:44.592985

"""

from alembic import op
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b329d00a9ea6"
down_revision = "f9b8c7d6e5a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant__user_specific_config",
        sa.Column("assistant_id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.Column("disabled_tool_ids", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.ForeignKeyConstraint(["assistant_id"], ["persona.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assistant_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("assistant__user_specific_config")
