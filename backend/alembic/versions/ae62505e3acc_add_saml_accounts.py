"""Add SAML Accounts

Revision ID: ae62505e3acc
Revises: 7da543f5672f
Create Date: 2023-09-26 16:19:30.933183

"""

import fastapi_users_db_sqlalchemy
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ae62505e3acc"
down_revision = "7da543f5672f"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "saml",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.Column("encrypted_cookie", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("encrypted_cookie"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("saml")
