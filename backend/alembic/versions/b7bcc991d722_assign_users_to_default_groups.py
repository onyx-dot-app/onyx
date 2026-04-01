"""assign_users_to_default_groups

Revision ID: b7bcc991d722
Revises: 03d085c5c38d
Create Date: 2026-03-25 16:30:39.529301

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert


# revision identifiers, used by Alembic.
revision = "b7bcc991d722"
down_revision = "03d085c5c38d"
branch_labels = None
depends_on = None

# Reflect table structures for use in DML
user_group_table = sa.table(
    "user_group",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("is_default", sa.Boolean),
)

user_table = sa.table(
    "user",
    sa.column("id", sa.Uuid),
    sa.column("role", sa.String),
    sa.column("account_type", sa.String),
    sa.column("is_active", sa.Boolean),
)

user__user_group_table = sa.table(
    "user__user_group",
    sa.column("user_group_id", sa.Integer),
    sa.column("user_id", sa.Uuid),
)


def upgrade() -> None:
    conn = op.get_bind()

    # Look up default group IDs
    admin_row = conn.execute(
        sa.select(user_group_table.c.id).where(
            user_group_table.c.name == "Admin",
            user_group_table.c.is_default == True,  # noqa: E712
        )
    ).fetchone()

    basic_row = conn.execute(
        sa.select(user_group_table.c.id).where(
            user_group_table.c.name == "Basic",
            user_group_table.c.is_default == True,  # noqa: E712
        )
    ).fetchone()

    if admin_row is None:
        raise RuntimeError(
            "Default 'Admin' group not found. "
            "Ensure migration 977e834c1427 (seed_default_groups) ran successfully."
        )

    if basic_row is None:
        raise RuntimeError(
            "Default 'Basic' group not found. "
            "Ensure migration 977e834c1427 (seed_default_groups) ran successfully."
        )

    # Users with role=admin → Admin group
    # Exclude inactive placeholder/anonymous users that are not real users
    admin_users = sa.select(
        sa.literal(admin_row[0]).label("user_group_id"),
        user_table.c.id.label("user_id"),
    ).where(
        user_table.c.role == "ADMIN",
        user_table.c.is_active == True,  # noqa: E712
    )
    op.execute(
        pg_insert(user__user_group_table)
        .from_select(["user_group_id", "user_id"], admin_users)
        .on_conflict_do_nothing(index_elements=["user_group_id", "user_id"])
    )

    # STANDARD users (non-admin) and SERVICE_ACCOUNT users (role=basic) → Basic group
    # Exclude inactive placeholder/anonymous users that are not real users
    basic_users = sa.select(
        sa.literal(basic_row[0]).label("user_group_id"),
        user_table.c.id.label("user_id"),
    ).where(
        user_table.c.is_active == True,  # noqa: E712
        sa.or_(
            sa.and_(
                user_table.c.account_type == "STANDARD",
                user_table.c.role != "ADMIN",
            ),
            sa.and_(
                user_table.c.account_type == "SERVICE_ACCOUNT",
                user_table.c.role == "BASIC",
            ),
        ),
    )
    op.execute(
        pg_insert(user__user_group_table)
        .from_select(["user_group_id", "user_id"], basic_users)
        .on_conflict_do_nothing(index_elements=["user_group_id", "user_id"])
    )


def downgrade() -> None:
    # Group memberships are left in place — removing them risks
    # deleting memberships that existed before this migration.
    pass
