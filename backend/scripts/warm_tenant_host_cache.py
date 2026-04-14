"""One-time script to warm the Redis tenant→host cache.

Iterates every configured Postgres host, discovers tenant schemas via
information_schema.schemata, and writes ``tenant_host:{tenant_id}`` = host_index
into Redis for each.  This avoids a thundering herd of control-plane calls
when multi-host routing is first enabled.

Usage:
    python scripts/warm_tenant_host_cache.py
"""

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_host_mapping import warm_tenant_host_cache
from onyx.db.engine.tenant_utils import get_tenant_ids_by_host
from onyx.utils.logger import setup_logger

logger = setup_logger()


def main() -> None:
    SqlEngine.init_all_engines(pool_size=5, max_overflow=2)

    by_host = get_tenant_ids_by_host()
    for host_index, tenants in by_host.items():
        logger.info(f"Host {host_index}: {len(tenants)} tenants")

    count = warm_tenant_host_cache(by_host)
    logger.info(f"Done — wrote {count} Redis entries")


if __name__ == "__main__":
    main()
