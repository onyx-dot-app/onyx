"""Writes to the `public.tenant_shard` catalog table.

Reads live in `onyx.db.engine.shard_routing`, which is on the request hot path and
caches aggressively. Writes happen at provisioning and teardown time only, so they go
straight to the catalog database with no caching.

Raw SQL against an explicitly schema-qualified name, matching the read side:
`schema_translate_map` only rewrites SQLAlchemy `Table` constructs, so an unqualified
name in `text()` would resolve against whatever `search_path` the pooled connection
happens to carry.
"""

from sqlalchemy import text

from onyx.db.engine.shard_registry import get_catalog_engine, is_default_shard
from onyx.db.engine.shard_routing import invalidate_shard_cache
from onyx.utils.logger import setup_logger

logger = setup_logger()


def record_tenant_placement(tenant_id: str, shard_name: str) -> None:
    """Record which physical database a tenant's schema is being created on.

    Must be called *before* the schema is created. Every provisioning step after that
    resolves the tenant's database through the catalog, so the mapping has to be there
    for them to reach the right one.

    Writes nothing for the default shard. An absent row already means "default", and
    keeping it that way leaves existing tenants and new ones described by one rule
    rather than splitting the fleet into mapped and unmapped halves.
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

    # A resolution attempted before this write would have cached "default" for a full
    # TTL, sending the schema to the wrong database. Local invalidation is enough: a
    # tenant this new cannot have been resolved anywhere else.
    invalidate_shard_cache(tenant_id)
    logger.info("Placed tenant %s on shard %s", tenant_id, shard_name)


def clear_tenant_placement(tenant_id: str) -> None:
    """Drop a tenant's shard mapping, for teardown paths.

    Leaving the row behind is inert — tenant IDs are UUIDs and are never reused — but
    it would misreport which shard is holding capacity.
    """
    with get_catalog_engine().connect() as connection:
        with connection.begin():
            connection.execute(
                text("DELETE FROM public.tenant_shard WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
