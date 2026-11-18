from sqlalchemy import create_engine, inspect, text

from onyx.configs.app_configs import POSTGRES_DB
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import upgrade_postgres


def test_integration_foreign_keys_have_full_indexes() -> None:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    engine = create_engine(build_connection_string(db=POSTGRES_DB, db_api=SYNC_DB_API))
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            for table, column in (
                ("integration_connection", "integration_id"),
                ("integration_action_policy", "integration_id"),
                ("integration", "created_by_user_id"),
            ):
                name = f"ix_{table}_{column}"
                indexes = {
                    index["name"]: index for index in inspector.get_indexes(table)
                }
                assert name in indexes, f"Missing full index: {name}"
                index = indexes[name]
                assert index["column_names"] == [column]
                assert not index.get("dialect_options", {}).get("postgresql_where")
                assert conn.execute(
                    text(
                        "SELECT indisvalid AND indisready FROM pg_index "
                        "WHERE indexrelid = to_regclass(:name)"
                    ),
                    {"name": f'"{conn.dialect.default_schema_name}"."{name}"'},
                ).scalar_one()
    finally:
        engine.dispose()
