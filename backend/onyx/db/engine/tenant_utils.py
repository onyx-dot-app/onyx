from sqlalchemy import text

from onyx.db.engine.sql_engine import SqlEngine
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import TENANT_ID_PREFIX


def _tenant_schemas_on_engine(host_index: int) -> list[str]:
    """Return tenant schema names that physically exist on the given host."""
    engine = SqlEngine.get_engine(host_index)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                f"""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN (
                    'pg_catalog', 'information_schema', '{POSTGRES_DEFAULT_SCHEMA}'
                )"""
            )
        )
        schemas = [row[0] for row in result]
    return [s for s in schemas if s.startswith(TENANT_ID_PREFIX)]


def get_tenant_ids_by_host() -> dict[int, list[str]]:
    """Return ``{host_index: [tenant_id, ...]}`` for every configured host."""
    if not MULTI_TENANT:
        return {0: [POSTGRES_DEFAULT_SCHEMA]}

    result: dict[int, list[str]] = {}
    for host_index in SqlEngine.get_all_engines():
        result[host_index] = _tenant_schemas_on_engine(host_index)
    return result


def get_all_tenant_ids() -> list[str]:
    """Flat list of all tenant IDs across every configured Postgres host."""
    if not MULTI_TENANT:
        return [POSTGRES_DEFAULT_SCHEMA]

    all_ids: list[str] = []
    for tenants in get_tenant_ids_by_host().values():
        all_ids.extend(tenants)
    return all_ids


def get_schemas_needing_migration(
    tenant_schemas: list[str], head_rev: str, host_index: int = 0
) -> list[str]:
    """Return only schemas whose current alembic version is not at head.

    Uses a server-side PL/pgSQL loop to collect each schema's alembic version
    into a temp table one at a time. This avoids building a massive UNION ALL
    query (which locks the DB and times out at 17k+ schemas) and instead
    acquires locks sequentially, one schema per iteration.
    """
    if not tenant_schemas:
        return []

    engine = SqlEngine.get_engine(host_index)

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS _alembic_version_snapshot"))
        conn.execute(text("DROP TABLE IF EXISTS _tenant_schemas_input"))
        conn.execute(text("CREATE TEMP TABLE _tenant_schemas_input (schema_name text)"))
        conn.execute(
            text(
                "INSERT INTO _tenant_schemas_input (schema_name) SELECT unnest(CAST(:schemas AS text[]))"
            ),
            {"schemas": tenant_schemas},
        )
        conn.execute(
            text(
                "CREATE TEMP TABLE _alembic_version_snapshot (schema_name text, version_num text)"
            )
        )

        conn.execute(
            text(
                """
                DO $$
                DECLARE
                    s        text;
                    schemas  text[];
                BEGIN
                    SELECT array_agg(schema_name) INTO schemas
                    FROM _tenant_schemas_input;

                    IF schemas IS NULL THEN
                        RAISE NOTICE 'No tenant schemas found.';
                        RETURN;
                    END IF;

                    FOREACH s IN ARRAY schemas LOOP
                        BEGIN
                            EXECUTE format(
                                'INSERT INTO _alembic_version_snapshot
                                 SELECT %L, version_num FROM %I.alembic_version',
                                s, s
                            );
                        EXCEPTION
                            WHEN undefined_table THEN NULL;
                            WHEN invalid_schema_name THEN NULL;
                        END;
                    END LOOP;
                END;
                $$
                """
            )
        )

        rows = conn.execute(
            text("SELECT schema_name, version_num FROM _alembic_version_snapshot")
        )
        version_by_schema = {row[0]: row[1] for row in rows}

        conn.execute(text("DROP TABLE IF EXISTS _alembic_version_snapshot"))
        conn.execute(text("DROP TABLE IF EXISTS _tenant_schemas_input"))

    return [s for s in tenant_schemas if version_by_schema.get(s) != head_rev]
