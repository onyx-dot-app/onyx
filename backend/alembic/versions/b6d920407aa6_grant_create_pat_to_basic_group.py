"""grant create:user_api_keys to the Basic group

Every member of the seeded Basic group may mint personal access tokens by default. The
grant is written as a SYSTEM row on the group and appended to its members'
stored permissions, since those are only recomputed on membership and grant
edits.

Revision ID: b6d920407aa6
Revises: c4d8e2f1a9b3

"""

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

# revision identifiers, used by Alembic.
revision = "b6d920407aa6"
down_revision = "c4d8e2f1a9b3"
branch_labels = None
depends_on = None

BASIC_GROUP_NAME = "Basic"
PERMISSION = "create:user_api_keys"
GRANT_SOURCE = "SYSTEM"

user_group_table: sa.TableClause = sa.table(
    "user_group",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("is_default", sa.Boolean),
)

permission_grant_table: sa.TableClause = sa.table(
    "permission_grant",
    sa.column("group_id", sa.Integer),
    sa.column("permission", sa.String),
    sa.column("grant_source", sa.String),
    sa.column("is_deleted", sa.Boolean),
)

user__user_group_table: sa.TableClause = sa.table(
    "user__user_group",
    sa.column("user_group_id", sa.Integer),
    sa.column("user_id", sa.Uuid),
)

user_table: sa.TableClause = sa.table(
    "user",
    sa.column("id", sa.Uuid),
    sa.column("effective_permissions", postgresql.JSONB),
)

permission_json: sa.BindParameter[list[str]] = sa.literal(
    [PERMISSION], type_=postgresql.JSONB
)

basic_group_id: sa.ScalarSelect[int] = (
    sa.select(user_group_table.c.id)
    .where(
        user_group_table.c.name == BASIC_GROUP_NAME,
        user_group_table.c.is_default.is_(True),
    )
    .scalar_subquery()
)

basic_member_ids: sa.Select[tuple[UUID]] = sa.select(
    user__user_group_table.c.user_id
).where(user__user_group_table.c.user_group_id == basic_group_id)


def upgrade() -> None:
    conn: sa.engine.Connection = op.get_bind()

    # A soft-deleted row would block the insert on the unique key, so revive it.
    conn.execute(
        pg_insert(permission_grant_table)
        .values(
            group_id=basic_group_id,
            permission=PERMISSION,
            grant_source=GRANT_SOURCE,
            is_deleted=False,
        )
        .on_conflict_do_update(
            index_elements=["group_id", "permission"],
            set_={"is_deleted": False},
        )
    )

    conn.execute(
        user_table.update()
        .where(
            user_table.c.id.in_(basic_member_ids),
            sa.not_(user_table.c.effective_permissions.contains(permission_json)),
        )
        .values(
            effective_permissions=user_table.c.effective_permissions.op("||")(
                permission_json
            )
        )
    )


def downgrade() -> None:
    conn: sa.engine.Connection = op.get_bind()

    conn.execute(
        sa.delete(permission_grant_table).where(
            permission_grant_table.c.group_id == basic_group_id,
            permission_grant_table.c.permission == PERMISSION,
        )
    )

    # Members who still hold the permission through another group keep it.
    other_grant_holders = (
        sa.select(user__user_group_table.c.user_id)
        .select_from(
            user__user_group_table.join(
                permission_grant_table,
                permission_grant_table.c.group_id
                == user__user_group_table.c.user_group_id,
            )
        )
        .where(
            user__user_group_table.c.user_id.is_not(None),
            permission_grant_table.c.permission == PERMISSION,
            permission_grant_table.c.is_deleted.is_(False),
        )
    )
    conn.execute(
        user_table.update()
        .where(
            user_table.c.id.in_(basic_member_ids),
            user_table.c.id.not_in(other_grant_holders),
        )
        .values(
            # jsonb - text drops the element. A JSONB bind would compile to the
            # undefined jsonb - jsonb.
            effective_permissions=user_table.c.effective_permissions.op("-")(
                sa.literal(PERMISSION, type_=sa.Text)
            )
        )
    )
