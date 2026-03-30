"""add_effective_permissions

Adds a JSONB column `effective_permissions` to the user table to store
directly granted permissions (e.g. ["admin"] or ["basic"]). Implied
permissions are expanded at read time, not stored.

Backfill: joins user__user_group → permission_grant to collect each
user's granted permissions into a sorted JSON array. Users without
group memberships keep the default [].

Revision ID: 503883791c39
Revises: b7bcc991d722
Create Date: 2026-03-30 14:49:22.261748

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "503883791c39"
down_revision = "b7bcc991d722"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "effective_permissions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            UPDATE "user" u
            SET effective_permissions = sub.perms
            FROM (
                SELECT user_id,
                       jsonb_agg(permission ORDER BY permission) AS perms
                FROM (
                    SELECT DISTINCT uug.user_id, pg.permission
                    FROM user__user_group uug
                    JOIN permission_grant pg
                      ON pg.group_id = uug.user_group_id
                     AND pg.is_deleted = false
                ) deduped
                GROUP BY user_id
            ) sub
            WHERE u.id = sub.user_id
            """
        )
    )


def downgrade() -> None:
    op.drop_column("user", "effective_permissions")
