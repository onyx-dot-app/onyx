import re
from itertools import chain

from sqlalchemy import text
from sqlalchemy.engine import Engine

from onyx.db.engine.shard_registry import (
    get_default_shard_name,
    get_engine_for_shard,
    get_shard_specs,
)
from shared_configs.configs import (
    MULTI_TENANT,
    POSTGRES_DEFAULT_SCHEMA,
    TENANT_ID_PREFIX,
)

# Regex pattern for valid tenant IDs:
# - UUID format: tenant_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# - AWS instance ID format: tenant_i-xxxxxxxxxxxxxxxxx
# - Staff dev tenant: tenant_dev
# Also useful for not accidentally dropping `public` schema.
TENANT_ID_PATTERN = re.compile(
    rf"^{re.escape(TENANT_ID_PREFIX)}("
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"  # UUID
    r"|i-[a-f0-9]+"  # AWS instance ID
    r"|dev"  # staff dev tenant
    r")$"
)


def validate_tenant_id(tenant_id: str) -> bool:
    """Validate that tenant_id matches expected format.

    This is important for SQL injection prevention since schema names
    cannot be parameterized in SQL and must be formatted directly.
    """
    return bool(TENANT_ID_PATTERN.match(tenant_id))


def get_schemas_needing_migration(
    tenant_schemas: list[str], head_rev: str, shard_name: str
) -> list[str]:
    """Return only schemas whose current alembic version is not at head.

    Uses a server-side PL/pgSQL loop to collect each schema's alembic version
    into a temp table one at a time. This avoids building a massive UNION ALL
    query (which locks the DB and times out at 17k+ schemas) and instead
    acquires locks sequentially, one schema per iteration.
    """
    if not tenant_schemas:
        return []

    # Named rather than defaulted: alembic_version lives in the schema, so this has to
    # read the database that actually holds these schemas.
    engine = get_engine_for_shard(shard_name)

    with engine.connect() as conn:
        # Populate a temp input table with exactly the schemas we care about.
        # The DO block reads from this table so it only iterates the requested
        # schemas instead of every tenant_% schema in the database.
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
            text("""
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
                """)
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


def _tenant_schemas_on(engine: Engine) -> list[str]:
    """Tenant schemas physically present in one database."""
    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema', :default_schema)"""
            ),
            {"default_schema": POSTGRES_DEFAULT_SCHEMA},
        )
        return [row[0] for row in result if validate_tenant_id(row[0])]


def get_tenant_ids_by_shard() -> dict[str, list[str]]:
    """Tenant schemas on each configured shard, keyed by shard name.

    Grouped by where a schema physically lives rather than by what `tenant_shard` says,
    because the callers that need the grouping — migrations — must reach the database
    actually holding the schema. A tenant mid-copy appears under both its old and its
    new shard, which is the safe way round: it gets migrated in both places.
    """
    if not MULTI_TENANT:
        return {get_default_shard_name(): [POSTGRES_DEFAULT_SCHEMA]}

    return {
        shard_name: _tenant_schemas_on(get_engine_for_shard(shard_name))
        for shard_name in sorted(get_shard_specs())
    }


def get_all_tenant_ids() -> list[str]:
    """Every tenant, across every shard.

    Returning [POSTGRES_DEFAULT_SCHEMA] means the only tenant is the 'public' or self
    hosted tenant. Enumerating a single shard would silently drop every tenant that has
    been moved off it — they would keep working, but stop being scheduled any work.
    """
    if not MULTI_TENANT:
        return [POSTGRES_DEFAULT_SCHEMA]

    # Deduped: a tenant mid-copy exists on two shards but is still one tenant.
    return sorted(set(chain.from_iterable(get_tenant_ids_by_shard().values())))
