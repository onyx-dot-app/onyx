"""Admin debug endpoints for live pod inspection.

Provides JSON endpoints for process info, pool state, threads,
and event loop lag. Only included when ENABLE_ADMIN_DEBUG_ENDPOINTS=true.
Requires admin authentication.
"""

import threading
import time
from typing import Any
from typing import cast

import psutil
from fastapi import APIRouter
from fastapi import Depends

from onyx.auth.users import current_admin_user

router = APIRouter(
    prefix="/admin/debug",
    tags=["debug"],
    dependencies=[Depends(current_admin_user)],
)

_process = psutil.Process()
_start_time: float | None = None


def set_start_time() -> None:
    """Capture server startup time. Called from lifespan()."""
    global _start_time
    if _start_time is None:
        _start_time = time.monotonic()


@router.get("/process-info")
def get_process_info() -> dict[str, Any]:
    """Return process-level resource info."""
    mem = _process.memory_info()
    uptime = round(time.monotonic() - _start_time, 1) if _start_time is not None else 0
    return {
        "rss_bytes": mem.rss,
        "vms_bytes": mem.vms,
        "cpu_percent": _process.cpu_percent(),
        "num_fds": _process.num_fds(),
        "num_threads": _process.num_threads(),
        "uptime_seconds": uptime,
    }


@router.get("/pool-state")
def get_pool_state() -> dict[str, Any]:
    """Return Postgres + Redis pool state as JSON."""
    result: dict[str, Any] = {"postgres": {}, "redis": {}}

    # Postgres pools
    try:
        from onyx.db.engine.sql_engine import SqlEngine
        from sqlalchemy.pool import QueuePool

        for label, engine in [
            ("sync", SqlEngine.get_engine()),
            ("readonly", SqlEngine.get_readonly_engine()),
        ]:
            pool = engine.pool
            if isinstance(pool, QueuePool):
                result["postgres"][label] = {
                    "checked_out": pool.checkedout(),
                    "checked_in": pool.checkedin(),
                    "overflow": pool.overflow(),
                    "size": pool.size(),
                }
    except Exception:
        result["postgres"]["error"] = "unable to read pool state"

    # Redis pools — uses private redis-py attributes (_in_use_connections, etc.)
    # because there is no public API for pool statistics.
    try:
        from redis import BlockingConnectionPool

        from onyx.redis.redis_pool import RedisPool

        pool_instance = RedisPool()
        pools: list[tuple[str, BlockingConnectionPool]] = [
            ("primary", cast(BlockingConnectionPool, pool_instance._pool)),
        ]
        if pool_instance._replica_pool is not None:
            pools.append(
                ("replica", cast(BlockingConnectionPool, pool_instance._replica_pool))
            )
        for label, rpool in pools:
            result["redis"][label] = {
                "in_use": len(rpool._in_use_connections),
                "available": len(rpool._available_connections),
                "max_connections": rpool.max_connections,
                "created_connections": rpool._created_connections,
            }
    except Exception:
        result["redis"]["error"] = "unable to read pool state"

    return result


@router.get("/threads")
def get_threads() -> list[dict[str, Any]]:
    """Return all threads via threading.enumerate()."""
    return [
        {
            "name": t.name,
            "daemon": t.daemon,
            "ident": t.ident,
            "alive": t.is_alive(),
        }
        for t in threading.enumerate()
    ]


@router.get("/event-loop-lag")
def get_event_loop_lag() -> dict[str, float]:
    """Return current and max event loop lag."""
    from onyx.server.metrics.event_loop_lag import get_current_lag
    from onyx.server.metrics.event_loop_lag import get_max_lag

    return {
        "current_lag_seconds": get_current_lag(),
        "max_lag_seconds": get_max_lag(),
    }
