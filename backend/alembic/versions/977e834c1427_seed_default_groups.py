"""seed_default_groups

Revision ID: 977e834c1427
Revises: a3f8b2c1d4e5
Create Date: 2026-03-25 14:59:41.313091

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "977e834c1427"
down_revision = "a3f8b2c1d4e5"
branch_labels = None
depends_on = None

# (group_name, permission_value)
DEFAULT_GROUPS = [
    ("Admin", "admin"),
    ("Basic", "basic"),
]

CUSTOM_SUFFIX = "(Custom)"


MAX_RENAME_ATTEMPTS = 100


def _find_available_name(conn: sa.engine.Connection, base: str) -> str:
    """Return a name like 'Admin (Custom)' or 'Admin (Custom 2)' that is not taken."""
    candidate = f"{base} {CUSTOM_SUFFIX}"
    attempt = 1
    while attempt <= MAX_RENAME_ATTEMPTS:
        exists = conn.execute(
            sa.text("SELECT 1 FROM user_group WHERE name = :name LIMIT 1"),
            {"name": candidate},
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
            sa.text("SELECT id, name FROM user_group " "WHERE name = :name"),
            {"name": group_name},
        ).fetchall()

        for row_id, row_name in conflicting:
            new_name = _find_available_name(conn, row_name)
            conn.execute(
                sa.text(
                    "UPDATE user_group "
                    "SET name = :new_name, is_up_to_date = false "
                    "WHERE id = :id"
                ),
                {"new_name": new_name, "id": row_id},
            )

        # Step 2: Create a fresh default group.
        result = conn.execute(
            sa.text(
                "INSERT INTO user_group "
                "(name, is_up_to_date, is_up_for_deletion, is_default) "
                "VALUES (:name, true, false, true) "
                "RETURNING id"
            ),
            {"name": group_name},
        ).fetchone()
        assert result is not None
        group_id = result[0]

        # Step 3: Upsert permission grant.
        conn.execute(
            sa.text(
                "INSERT INTO permission_grant (group_id, permission, grant_source) "
                "VALUES (:group_id, :permission, 'system') "
                "ON CONFLICT (group_id, permission) DO NOTHING"
            ),
            {"group_id": group_id, "permission": permission_value},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove the default groups created by this migration.
    # Permission grants cascade-delete via FK.
    conn.execute(sa.text("DELETE FROM user_group WHERE is_default = true"))
