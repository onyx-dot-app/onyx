"""group_permissions_phase1

Revision ID: 25a5501dc766
Revises: b728689f45b1
Create Date: 2026-03-23 11:41:25.557442

"""

from alembic import op
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa

from onyx.db.enums import AccountType
from onyx.db.enums import GrantSource
from onyx.db.enums import Permission


# revision identifiers, used by Alembic.
revision = "25a5501dc766"
down_revision = "b728689f45b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add account_type column to user table (nullable for now,
    #    a future migration will backfill and set NOT NULL)
    op.add_column(
        "user",
        sa.Column(
            "account_type",
            sa.Enum(AccountType, native_enum=False),
            nullable=True,
        ),
    )

    # 2. Add is_default column to user_group table
    op.add_column(
        "user_group",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # 3. Create permission_grant table
    op.create_table(
        "permission_grant",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column(
            "permission",
            sa.Enum(Permission, native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "grant_source",
            sa.Enum(GrantSource, native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "granted_by",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["user_group.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["user.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("group_id", "permission"),
    )

    # 4. Index on user__user_group(user_id) — existing composite PK
    #    has user_group_id as leading column; user-filtered queries need this
    op.create_index(
        "ix_user__user_group_user_id",
        "user__user_group",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user__user_group_user_id", table_name="user__user_group")
    op.drop_table("permission_grant")
    op.drop_column("user_group", "is_default")
    op.drop_column("user", "account_type")
