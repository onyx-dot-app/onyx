"""How many tenant schemas each physical database is holding.

Schema-per-tenant is bounded by catalog size rather than disk: every tenant adds
~110 tables, so the table count — and with it migration wall-clock and autovacuum
pressure — scales with tenants, not bytes. This is the signal for when to move new
signups onto another shard.
"""

import threading
import time
from collections.abc import Iterator

from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from onyx.db.engine.shard_registry import get_shard_specs
from onyx.db.engine.tenant_utils import count_tenant_schemas_on_shard
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

_CACHE_TTL_SECONDS = 300.0


class ShardCapacityCollector(Collector):
    """Publishes the tenant count per shard, computed on scrape.

    Deliberately not a periodic task. Beat dispatches a task to exactly one worker,
    so only that replica's process would hold the value while the other monitoring
    pods published nothing — and replacing that pod would blank the series until the
    next run. Collecting on scrape keeps every replica current, so the alert cannot
    go blind on a rollout.

    Cached so the scrape interval does not drive database load.
    """

    def __init__(self, ttl_seconds: float = _CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._expires_at = 0.0

    def _tenant_counts(self) -> dict[str, int]:
        # The refresh runs under the lock, not just the cache read. Releasing it around
        # the scan would let concurrent scrapes each run their own, and let a slower
        # older refresh overwrite a newer result on the way out. A scrape that arrives
        # mid-refresh waits and then reads the fresh value.
        with self._lock:
            if time.monotonic() < self._expires_at:
                return self._counts

            counts: dict[str, int] = {}
            for shard_name in sorted(get_shard_specs()):
                try:
                    counts[shard_name] = count_tenant_schemas_on_shard(shard_name)
                except Exception:
                    # Per shard: one unreachable database must not suppress the others.
                    # A capacity alert that goes blank during an unrelated outage is
                    # worse than one missing a single series.
                    logger.exception("Failed counting tenants on shard %s", shard_name)

            self._counts = counts
            self._expires_at = time.monotonic() + self._ttl
            return counts

    def collect(self) -> Iterator[Metric]:
        gauge = GaugeMetricFamily(
            "onyx_shard_tenant_count",
            "Tenant schemas physically present on a shard",
            labels=["shard"],
        )
        if MULTI_TENANT:
            for shard_name, count in self._tenant_counts().items():
                gauge.add_metric([shard_name], count)
        yield gauge
