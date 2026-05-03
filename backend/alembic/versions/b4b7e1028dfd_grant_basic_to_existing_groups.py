"""grant_basic_to_existing_groups

Grants the "basic" permission to all existing groups that don't already
have it. Every group should have at least "basic" so that its members
get basic access when effective_permissions is backfilled.

Revision ID: b4b7e1028dfd
Revises: b7bcc991d722
Create Date: 2026-03-30 16:15:17.093498

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b4b7e1028dfd"
down_revision = "b7bcc991d722"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None

user_group = sa.table(
    "user_group",
    sa.column("id", sa.Integer),
    sa.column("is_default", sa.Boolean),
)

permission_grant = sa.table(
    "permission_grant",
    sa.column("group_id", sa.Integer),
    sa.column("permission", sa.String),
    sa.column("grant_source", sa.String),
    sa.column("is_deleted", sa.Boolean),
)


def upgrade() -> None:
    conn = op.get_bind()

    already_has_basic = (
        sa.select(sa.literal(1))
        .select_from(permission_grant)
        .where(
            permission_grant.c.group_id == user_group.c.id,
            permission_grant.c.permission == "basic",
        )
        .exists()
    )

    groups_needing_basic = sa.select(
        user_group.c.id,
        sa.literal("basic").label("permission"),
        sa.literal("SYSTEM").label("grant_source"),
        sa.literal(False).label("is_deleted"),
    ).where(
        user_group.c.is_default == sa.false(),
        ~already_has_basic,
    )

    conn.execute(
        permission_grant.insert().from_select(
            ["group_id", "permission", "grant_source", "is_deleted"],
            groups_needing_basic,
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    non_default_group_ids = sa.select(user_group.c.id).where(
        user_group.c.is_default == sa.false()
    )

    conn.execute(
        permission_grant.delete().where(
            permission_grant.c.permission == "basic",
            permission_grant.c.grant_source == "SYSTEM",
            permission_grant.c.group_id.in_(non_default_group_ids),
        )
    )
