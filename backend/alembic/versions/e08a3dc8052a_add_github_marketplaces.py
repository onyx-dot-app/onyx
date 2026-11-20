"""add github marketplaces

A GitHub marketplace is a plugin_marketplace row of kind 'github'. It keeps its
repository, its login user and the state of its last sync. Each synced plugin
keeps the key of its marketplace entry, and each synced version keeps the git
tree of its folder.

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

LOCK_TIMEOUT = "60s"
ENTRY_KEY_INDEX = "uq_plugin_marketplace_entry_key"
OLD_OWNER_CHECK = "ck_plugin_marketplace_owner_iff_user_uploads"
OWNER_CHECK = "ck_plugin_marketplace_owner_by_kind"
LOGIN_USER_FK = "fk_plugin_marketplace_login_user"


def _index_state(conn: sa.engine.Connection, qualified_name: str) -> bool | None:
    """An interrupted concurrent build can leave an invalid index."""
    return conn.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:qualified_name)"
        ),
        {"qualified_name": qualified_name},
    ).scalar_one_or_none()


def upgrade() -> None:
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # A retry after the commit below skips the metadata phase.
    if "provider_config" not in {
        column["name"]
        for column in sa.inspect(bind).get_columns("plugin_marketplace", schema=schema)
    }:
        _add_columns()
    # Release DDL locks before the concurrent index build. env.py owns the
    # transaction, so Alembic's autocommit_block cannot be used.
    bind.commit()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        try:
            _build_index_and_validate(conn, schema)
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def _add_columns() -> None:
    for column in (
        sa.Column("provider_config", postgresql.JSONB(), nullable=True),
        sa.Column("login_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_synced_revision", sa.String(length=40), nullable=True),
        sa.Column("last_synced_tree_sha", sa.String(length=40), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sync_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_delete_revision", sa.String(length=40), nullable=True),
        sa.Column("last_sync_result", postgresql.JSONB(), nullable=True),
    ):
        op.add_column("plugin_marketplace", column)
    op.create_foreign_key(
        LOGIN_USER_FK,
        "plugin_marketplace",
        "user",
        ["login_user_id"],
        ["id"],
        ondelete="SET NULL",
        postgresql_not_valid=True,
    )
    op.add_column(
        "plugin",
        sa.Column("marketplace_entry_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "plugin_version",
        sa.Column("source_tree_sha", sa.String(length=40), nullable=True),
    )
    op.drop_constraint(OLD_OWNER_CHECK, "plugin_marketplace", type_="check")
    op.create_check_constraint(
        OWNER_CHECK,
        "plugin_marketplace",
        "(kind = 'user_uploads' AND owner_user_id IS NOT NULL) "
        "OR (kind = 'organization_library' AND owner_user_id IS NULL) "
        "OR kind = 'github'",
        postgresql_not_valid=True,
    )


def _build_index_and_validate(conn: sa.engine.Connection, schema: str) -> None:
    quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
    qualified_name = f'{quoted_schema}."{ENTRY_KEY_INDEX}"'
    state = _index_state(conn, qualified_name)
    if state is False:
        conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY {qualified_name}")
    if state is not True:
        conn.exec_driver_sql(
            f'CREATE UNIQUE INDEX CONCURRENTLY "{ENTRY_KEY_INDEX}" '
            f"ON {quoted_schema}.plugin (marketplace_id, marketplace_entry_key) "
            "WHERE marketplace_entry_key IS NOT NULL"
        )
    for constraint in (OWNER_CHECK, LOGIN_USER_FK):
        conn.exec_driver_sql(
            f"ALTER TABLE {quoted_schema}.plugin_marketplace "
            f"VALIDATE CONSTRAINT {constraint}"
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM plugin WHERE marketplace_id IN "
        "(SELECT id FROM plugin_marketplace WHERE kind = 'github')"
    )
    op.execute("DELETE FROM plugin_marketplace WHERE kind = 'github'")
    op.drop_index(ENTRY_KEY_INDEX, table_name="plugin")
    op.drop_constraint(OWNER_CHECK, "plugin_marketplace", type_="check")
    op.drop_constraint(LOGIN_USER_FK, "plugin_marketplace", type_="foreignkey")
    op.drop_column("plugin_version", "source_tree_sha")
    op.drop_column("plugin", "marketplace_entry_key")
    for column in (
        "last_sync_result",
        "pending_delete_revision",
        "sync_requested_at",
        "last_error",
        "last_synced_at",
        "last_synced_tree_sha",
        "last_synced_revision",
        "login_user_id",
        "provider_config",
    ):
        op.drop_column("plugin_marketplace", column)
    op.create_check_constraint(
        OLD_OWNER_CHECK,
        "plugin_marketplace",
        "(kind = 'user_uploads') = (owner_user_id IS NOT NULL)",
    )
