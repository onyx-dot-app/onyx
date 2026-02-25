from sqlalchemy import text

from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.engine.sql_engine import SqlEngine
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import TENANT_ID_PREFIX


def get_schemas_needing_migration(
    tenant_schemas: list[str], head_rev: str
) -> list[str]:
    """Return only schemas whose current alembic version is not at head.

    Uses a server-side PL/pgSQL loop to collect each schema's alembic version
    into a temp table one at a time. This avoids building a massive UNION ALL
    query (which locks the DB and times out at 17k+ schemas) and instead
    acquires locks sequentially, one schema per iteration.
    """
    if not tenant_schemas:
        return []

    engine = SqlEngine.get_engine()

    with engine.connect() as conn:
        # Populate a temp input table with exactly the schemas we care about.
        # The DO block reads from this table so it only iterates the requested
        # schemas instead of every tenant_% schema in the database.
        conn.execute(text("DROP TABLE IF EXISTS _alembic_version_snapshot"))
        conn.execute(text("DROP TABLE IF EXISTS _tenant_schemas_input"))
        conn.execute(text("CREATE TEMP TABLE _tenant_schemas_input (schema_name text)"))
        conn.execute(
            text(
                "INSERT INTO _tenant_schemas_input (schema_name) "
                "SELECT unnest(CAST(:schemas AS text[]))"
            ),
            {"schemas": tenant_schemas},
        )
        conn.execute(
            text(
                "CREATE TEMP TABLE _alembic_version_snapshot "
                "(schema_name text, version_num text)"
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
                            -- undefined_table: schema exists but has no alembic_version
                            --   table yet (new tenant, not yet migrated).
                            -- invalid_schema_name: tenant is registered but its
                            --   PostgreSQL schema does not exist yet (e.g. provisioning
                            --   incomplete). Both cases mean no version is available and
                            --   the schema will be included in the migration list.
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

    # Schemas missing from the snapshot have no alembic_version table yet and
    # also need migration. version_by_schema.get(s) returns None for those,
    # and None != head_rev, so they are included automatically.
    return [s for s in tenant_schemas if version_by_schema.get(s) != head_rev]


def get_all_tenant_ids() -> list[str]:
    """Returning [None] means the only tenant is the 'public' or self hosted tenant."""

    tenant_ids: list[str]

    if not MULTI_TENANT:
        return [POSTGRES_DEFAULT_SCHEMA]

    with get_session_with_shared_schema() as session:
        result = session.execute(
            text(
                f"""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema', '{POSTGRES_DEFAULT_SCHEMA}')"""
            )
        )
        tenant_ids = [row[0] for row in result]

    valid_tenants = [
        tenant
        for tenant in tenant_ids
        if tenant is None or tenant.startswith(TENANT_ID_PREFIX)
    ]
    return valid_tenants
