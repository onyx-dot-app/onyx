"""Writes to the `public.tenant_shard` catalog table. Reads live in `shard_routing`.

Schema-qualified raw SQL, matching the read side: `schema_translate_map` only rewrites
SQLAlchemy `Table` constructs, so an unqualified name in `text()` would resolve against
whatever `search_path` the pooled connection happens to carry.
"""

from sqlalchemy import text

from onyx.db.engine.shard_registry import get_catalog_engine, is_default_shard
from onyx.db.engine.shard_routing import invalidate_shard_cache, is_undefined_table
from onyx.utils.logger import setup_logger

logger = setup_logger()


def record_tenant_placement(tenant_id: str, shard_name: str) -> None:
    """Record where a tenant's schema is about to be created.

    Must run *before* schema creation: every step after it resolves the tenant's
    database through the catalog. Writes nothing for the default shard, since an
    absent row already means "default".
    """
    if is_default_shard(shard_name):
        return

    with get_catalog_engine().connect() as connection:
        with connection.begin():
            connection.execute(
                text(
                    """
                    INSERT INTO public.tenant_shard (tenant_id, shard_name)
                    VALUES (:tenant_id, :shard_name)
                    ON CONFLICT (tenant_id)
                    DO UPDATE SET shard_name = EXCLUDED.shard_name, updated_at = now()
                    """
                ),
                {"tenant_id": tenant_id, "shard_name": shard_name},
            )

    # A lookup before this write caches "default" for a full TTL, which would send the
    # schema to the wrong database. Local-only: nothing else has seen this tenant.
    invalidate_shard_cache(tenant_id)
    logger.info("Placed tenant %s on shard %s", tenant_id, shard_name)


def clear_tenant_placement(tenant_id: str) -> None:
    """Drop a tenant's shard mapping. Inert if left behind, since tenant ids are never
    reused, but it would misreport which shard is holding capacity.

    Tolerates a missing table, matching the read path: teardown runs on every
    deployment, including one that has not applied the catalog migration, and nothing
    can be mapped there anyway. The insert deliberately does not — reaching it means
    shards are configured, so the table has to exist.
    """
    try:
        with get_catalog_engine().connect() as connection:
            with connection.begin():
                connection.execute(
                    text(
                        "DELETE FROM public.tenant_shard WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
    except Exception as e:
        if not is_undefined_table(e):
            raise
        logger.debug("public.tenant_shard does not exist; nothing to clear")
