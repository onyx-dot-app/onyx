"""add_scim_tables

Revision ID: 9c54986124c6
Revises: b51c6844d1df
Create Date: 2026-02-12 20:29:47.448614

"""

from alembic import op
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9c54986124c6"
down_revision = "b51c6844d1df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scim_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hashed_token", sa.String(length=64), nullable=False),
        sa.Column("token_display", sa.String(), nullable=False),
        sa.Column(
            "created_by_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hashed_token"),
    )
    op.create_table(
        "scim_group_mapping",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("user_group_id", sa.Integer(), nullable=False),
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
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_group_id"], ["user_group.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_group_id"),
    )
    op.create_index(
        op.f("ix_scim_group_mapping_external_id"),
        "scim_group_mapping",
        ["external_id"],
        unique=True,
    )
    op.create_table(
        "scim_user_mapping",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
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
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_scim_user_mapping_external_id"),
        "scim_user_mapping",
        ["external_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_scim_user_mapping_external_id"),
        table_name="scim_user_mapping",
    )
    op.drop_table("scim_user_mapping")
    op.drop_index(
        op.f("ix_scim_group_mapping_external_id"),
        table_name="scim_group_mapping",
    )
    op.drop_table("scim_group_mapping")
    op.drop_table("scim_token")
