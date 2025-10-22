"""add_oauth_config_and_user_tokens

Revision ID: 3d1cca026fe8
Revises: c8a93a2af083
Create Date: 2025-10-21 13:27:34.274721

"""

from alembic import op
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "3d1cca026fe8"
down_revision = "c8a93a2af083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create oauth_config table
    op.create_table(
        "oauth_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("authorization_url", sa.Text(), nullable=False),
        sa.Column("token_url", sa.Text(), nullable=False),
        sa.Column("client_id", sa.LargeBinary(), nullable=False),
        sa.Column("client_secret", sa.LargeBinary(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "additional_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Create oauth_user_token table
    op.create_table(
        "oauth_user_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("oauth_config_id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.Column("token_data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["oauth_config_id"], ["oauth_config.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("oauth_config_id", "user_id", name="uq_oauth_user_token"),
    )

    # Create index on user_id for efficient user-based token lookups
    # Note: unique constraint on (oauth_config_id, user_id) already creates
    # an index for config-based lookups
    op.create_index(
        "ix_oauth_user_token_user_id",
        "oauth_user_token",
        ["user_id"],
    )

    # Add oauth_config_id column to tool table
    op.add_column("tool", sa.Column("oauth_config_id", sa.Integer(), nullable=True))

    # Create foreign key from tool to oauth_config
    op.create_foreign_key(
        "tool_oauth_config_fk",
        "tool",
        "oauth_config",
        ["oauth_config_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Drop foreign key from tool to oauth_config
    op.drop_constraint("tool_oauth_config_fk", "tool", type_="foreignkey")

    # Drop oauth_config_id column from tool table
    op.drop_column("tool", "oauth_config_id")

    # Drop index on user_id
    op.drop_index("ix_oauth_user_token_user_id", table_name="oauth_user_token")

    # Drop oauth_user_token table (will cascade delete tokens)
    op.drop_table("oauth_user_token")

    # Drop oauth_config table
    op.drop_table("oauth_config")
