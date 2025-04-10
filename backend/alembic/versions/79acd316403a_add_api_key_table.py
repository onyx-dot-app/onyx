"""Add api_key table

Revision ID: 79acd316403a
Revises: 904e5138fffb
Create Date: 2024-01-11 17:56:37.934381

"""

from alembic import op
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "79acd316403a"
down_revision = "904e5138fffb"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hashed_api_key", sa.String(), nullable=False),
        sa.Column("api_key_display", sa.String(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key_display"),
        sa.UniqueConstraint("hashed_api_key"),
    )


def downgrade() -> None:
    op.drop_table("api_key")
