"""add_effective_permissions

Adds a JSONB column `effective_permissions` to the user table to store
directly granted permissions (e.g. ["admin"] or ["basic"]). Implied
permissions are expanded at read time, not stored.

Backfill: joins user__user_group → permission_grant to collect each
user's granted permissions into a sorted JSON array. Users without
group memberships keep the default [].

Revision ID: 503883791c39
Revises: b4b7e1028dfd
Create Date: 2026-03-30 14:49:22.261748

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "503883791c39"
down_revision = "b4b7e1028dfd"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None

user_table = sa.table(
    "user",
    sa.column("id", sa.Uuid),
    sa.column("effective_permissions", postgresql.JSONB),
)

user_user_group = sa.table(
    "user__user_group",
    sa.column("user_id", sa.Uuid),
    sa.column("user_group_id", sa.Integer),
)

permission_grant = sa.table(
    "permission_grant",
    sa.column("group_id", sa.Integer),
    sa.column("permission", sa.String),
    sa.column("is_deleted", sa.Boolean),
)


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

    # Deduplicated permissions per user
    deduped = (
        sa.select(
            user_user_group.c.user_id,
            permission_grant.c.permission,
        )
        .select_from(
            user_user_group.join(
                permission_grant,
                sa.and_(
                    permission_grant.c.group_id == user_user_group.c.user_group_id,
                    permission_grant.c.is_deleted == sa.false(),
                ),
            )
        )
        .distinct()
        .subquery("deduped")
    )

    # Aggregate into sorted JSONB array per user
    perms_per_user = (
        sa.select(
            deduped.c.user_id,
            sa.func.jsonb_agg(
                deduped.c.permission,
                type_=postgresql.JSONB,
            ).label("perms"),
        )
        .group_by(deduped.c.user_id)
        .subquery("sub")
    )

    conn.execute(
        user_table.update()
        .where(user_table.c.id == perms_per_user.c.user_id)
        .values(effective_permissions=perms_per_user.c.perms)
    )


def downgrade() -> None:
    op.drop_column("user", "effective_permissions")
