"""seed_default_groups

Revision ID: 977e834c1427
Revises: 8188861f4e92
Create Date: 2026-03-25 14:59:41.313091

"""

from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

# revision identifiers, used by Alembic.
revision = "977e834c1427"
down_revision = "8188861f4e92"
branch_labels = None
depends_on = None

# (group_name, permission_value)
DEFAULT_GROUPS = [
    ("Admin", "admin"),
    ("Basic", "basic"),
]

CUSTOM_SUFFIX = "(Custom)"

MAX_RENAME_ATTEMPTS = 100

# Reflect table structures for use in DML
user_group_table = sa.table(
    "user_group",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("is_up_to_date", sa.Boolean),
    sa.column("is_up_for_deletion", sa.Boolean),
    sa.column("is_default", sa.Boolean),
)

permission_grant_table = sa.table(
    "permission_grant",
    sa.column("group_id", sa.Integer),
    sa.column("permission", sa.String),
    sa.column("grant_source", sa.String),
)

user__user_group_table = sa.table(
    "user__user_group",
    sa.column("user_group_id", sa.Integer),
    sa.column("user_id", sa.Uuid),
)


def _find_available_name(conn: sa.engine.Connection, base: str) -> str:
    """Return a name like 'Admin (Custom)' or 'Admin (Custom 2)' that is not taken."""
    candidate = f"{base} {CUSTOM_SUFFIX}"
    attempt = 1
    while attempt <= MAX_RENAME_ATTEMPTS:
        exists: Any = conn.execute(
            sa.select(sa.literal(1))
            .select_from(user_group_table)
            .where(user_group_table.c.name == candidate)
            .limit(1)
        ).fetchone()
        if exists is None:
            return candidate
        attempt += 1
        candidate = f"{base} (Custom {attempt})"
    raise RuntimeError(
        f"Could not find an available name for group '{base}' "
        f"after {MAX_RENAME_ATTEMPTS} attempts"
    )


def upgrade() -> None:
    conn = op.get_bind()

    for group_name, permission_value in DEFAULT_GROUPS:
        # Step 1: Rename ALL existing groups that clash with the canonical name.
        conflicting = conn.execute(
            sa.select(user_group_table.c.id, user_group_table.c.name).where(
                user_group_table.c.name == group_name
            )
        ).fetchall()

        for row_id, row_name in conflicting:
            new_name = _find_available_name(conn, row_name)
            op.execute(
                sa.update(user_group_table)
                .where(user_group_table.c.id == row_id)
                .values(name=new_name, is_up_to_date=False)
            )

        # Step 2: Create a fresh default group.
        result = conn.execute(
            user_group_table.insert()
            .values(
                name=group_name,
                is_up_to_date=True,
                is_up_for_deletion=False,
                is_default=True,
            )
            .returning(user_group_table.c.id)
        ).fetchone()
        assert result is not None
        group_id = result[0]

        # Step 3: Upsert permission grant.
        op.execute(
            pg_insert(permission_grant_table)
            .values(
                group_id=group_id,
                permission=permission_value,
                grant_source="SYSTEM",
            )
            .on_conflict_do_nothing(index_elements=["group_id", "permission"])
        )


def downgrade() -> None:
    # Remove the default groups created by this migration.
    # First remove user-group memberships that reference default groups
    # to avoid FK violations, then delete the groups themselves.
    default_group_ids = sa.select(user_group_table.c.id).where(
        user_group_table.c.is_default == True  # noqa: E712
    )
    conn = op.get_bind()
    conn.execute(
        sa.delete(user__user_group_table).where(
            user__user_group_table.c.user_group_id.in_(default_group_ids)
        )
    )
    conn.execute(
        sa.delete(user_group_table).where(
            user_group_table.c.is_default == True  # noqa: E712
        )
    )
