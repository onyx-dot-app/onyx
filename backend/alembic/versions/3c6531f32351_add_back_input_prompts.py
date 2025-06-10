"""add back input prompts

Revision ID: 3c6531f32351
Revises: aeda5f2df4f6
Create Date: 2025-01-13 12:49:51.705235

"""

from alembic import op
import sqlalchemy as sa
import fastapi_users_db_sqlalchemy

# revision identifiers, used by Alembic.
revision = "3c6531f32351"
down_revision = "aeda5f2df4f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inputprompt",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prompt", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "inputprompt__user",
        sa.Column("input_prompt_id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False
        ),
        sa.Column("disabled", sa.Boolean(), nullable=False, default=False),
        sa.ForeignKeyConstraint(
            ["input_prompt_id"],
            ["inputprompt.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("input_prompt_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("inputprompt__user")
    op.drop_table("inputprompt")
