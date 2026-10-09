"""add is_manager and is_group_manager

Per-(user, group) ``is_manager`` edge + cached ``user.is_group_manager`` boolean
for the group-manager feature. Additive, ``false`` server default.

Role-gated backfill preserves the curator signal before ``role`` / ``is_curator``
are dropped later: ``CURATOR`` -> their curated groups; ``GLOBAL_CURATOR`` -> every
membership. Must run before any release drops ``role`` / ``is_curator``.

Revision ID: c71a18ea7d07
Revises: c8e316473aaa
Create Date: 2026-06-29 14:15:32.889597

"""

from alembic import op
import sqlalchemy as sa

revision = "c71a18ea7d07"
down_revision = "c8e316473aaa"
branch_labels = None
depends_on = None

# role compares against the enum NAME (Enum(native_enum=False)) — uppercase.
user_table = sa.table(
    "user",
    sa.column("id", sa.Uuid),
    sa.column("role", sa.String),
    sa.column("is_group_manager", sa.Boolean),
)
user_user_group = sa.table(
    "user__user_group",
    sa.column("user_id", sa.Uuid),
    sa.column("user_group_id", sa.Integer),
    sa.column("is_curator", sa.Boolean),
    sa.column("is_manager", sa.Boolean),
)
user_group = sa.table(
    "user_group",
    sa.column("id", sa.Integer),
    sa.column("is_default", sa.Boolean),
)


def upgrade() -> None:
    op.add_column(
        "user__user_group",
        sa.Column(
            "is_manager",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "user",
        sa.Column(
            "is_group_manager",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # Never seed a manager edge on a default group: "Basic" holds the whole org, so it
    # would grant org-wide scope. (CURATOR can't curate a default group today; carried
    # for safety.)
    default_group_ids = sa.select(user_group.c.id).where(
        user_group.c.is_default == sa.true()
    )
    op.execute(
        sa.update(user_user_group)
        .where(
            user_user_group.c.user_id == user_table.c.id,
            user_table.c.role == "CURATOR",
            user_user_group.c.is_curator == sa.true(),
            user_user_group.c.user_group_id.notin_(default_group_ids),
        )
        .values(is_manager=sa.true())
    )
    # GLOBAL_CURATOR has no is_curator rows — every non-default membership becomes managed.
    op.execute(
        sa.update(user_user_group)
        .where(
            user_user_group.c.user_id == user_table.c.id,
            user_table.c.role == "GLOBAL_CURATOR",
            user_user_group.c.user_group_id.notin_(default_group_ids),
        )
        .values(is_manager=sa.true())
    )
    managed_user_ids = (
        sa.select(user_user_group.c.user_id)
        .where(user_user_group.c.is_manager == sa.true())
        .distinct()
    )
    op.execute(
        sa.update(user_table)
        .where(user_table.c.id.in_(managed_user_ids))
        .values(is_group_manager=sa.true())
    )


def downgrade() -> None:
    op.drop_column("user", "is_group_manager")
    op.drop_column("user__user_group", "is_manager")
