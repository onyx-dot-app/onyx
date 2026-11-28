"""add github marketplaces

A GitHub marketplace is a plugin_marketplace row of kind 'github'. It keeps its
repository, its login user and the state of its last sync.

Revision ID: e08a3dc8052a
Revises: 2d7510746863
Create Date: 2026-11-19 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e08a3dc8052a"
down_revision = "2d7510746863"
branch_labels = None
depends_on = None

OLD_OWNER_CHECK = "ck_plugin_marketplace_owner_iff_user_uploads"
OWNER_CHECK = "ck_plugin_marketplace_owner_by_kind"
LOGIN_USER_FK = "fk_plugin_marketplace_login_user"
PERSONAL_SOURCE_INDEX = "uq_plugin_marketplace_personal_source"
COMPANY_SOURCE_INDEX = "uq_plugin_marketplace_company_source"
SOURCE_COLUMNS = ["repository", "folder", "ref"]


def upgrade() -> None:
    op.add_column("plugin_marketplace", sa.Column("repository", sa.String()))
    # '' not NULL: the unique indexes dedup pre-PG15 without NULLS NOT DISTINCT.
    for name in ("folder", "ref"):
        op.add_column(
            "plugin_marketplace",
            sa.Column(name, sa.String(), nullable=False, server_default=""),
        )
    op.add_column(
        "plugin_marketplace",
        sa.Column("login_user_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "plugin_marketplace", sa.Column("last_synced_revision", sa.String(40))
    )
    op.add_column(
        "plugin_marketplace",
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
    )
    op.add_column("plugin_marketplace", sa.Column("last_error", sa.Text()))
    op.add_column(
        "plugin_marketplace", sa.Column("last_sync_result", postgresql.JSONB())
    )
    op.create_foreign_key(  # migration-design: allow not-valid - plugin_marketplace has one row per user plus GitHub rows
        LOGIN_USER_FK,
        "plugin_marketplace",
        "user",
        ["login_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(OLD_OWNER_CHECK, "plugin_marketplace", type_="check")
    op.create_check_constraint(  # migration-design: allow not-valid - plugin_marketplace has one row per user plus GitHub rows
        OWNER_CHECK,
        "plugin_marketplace",
        "(kind = 'user_uploads' AND owner_user_id IS NOT NULL) "
        "OR (kind = 'organization_library' AND owner_user_id IS NULL) "
        "OR (kind = 'github' AND repository IS NOT NULL)",
    )
    op.create_index(  # migration-design: allow blocking-index - plugin_marketplace has one row per user plus GitHub rows
        PERSONAL_SOURCE_INDEX,
        "plugin_marketplace",
        ["owner_user_id", *SOURCE_COLUMNS],
        unique=True,
        postgresql_where=sa.text("kind = 'github' AND owner_user_id IS NOT NULL"),
    )
    op.create_index(  # migration-design: allow blocking-index - plugin_marketplace has one row per user plus GitHub rows
        COMPANY_SOURCE_INDEX,
        "plugin_marketplace",
        SOURCE_COLUMNS,
        unique=True,
        postgresql_where=sa.text("kind = 'github' AND owner_user_id IS NULL"),
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM plugin WHERE marketplace_id IN "
        "(SELECT id FROM plugin_marketplace WHERE kind = 'github')"
    )
    op.execute("DELETE FROM plugin_marketplace WHERE kind = 'github'")
    op.drop_index(COMPANY_SOURCE_INDEX, table_name="plugin_marketplace")
    op.drop_index(PERSONAL_SOURCE_INDEX, table_name="plugin_marketplace")
    op.drop_constraint(OWNER_CHECK, "plugin_marketplace", type_="check")
    op.drop_constraint(LOGIN_USER_FK, "plugin_marketplace", type_="foreignkey")
    for column in (
        "last_sync_result",
        "last_error",
        "last_synced_at",
        "last_synced_revision",
        "login_user_id",
        *SOURCE_COLUMNS,
    ):
        op.drop_column("plugin_marketplace", column)
    op.create_check_constraint(
        OLD_OWNER_CHECK,
        "plugin_marketplace",
        "(kind = 'user_uploads') = (owner_user_id IS NOT NULL)",
    )
