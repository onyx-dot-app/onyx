"""Admin debug endpoints for live pod inspection.

Provides JSON endpoints for process info, pool state, threads,
and event loop lag. Only included when ENABLE_ADMIN_DEBUG_ENDPOINTS=true.
Requires admin authentication.
"""

import os
import threading
import time
from typing import Any
from typing import cast

import psutil
from fastapi import APIRouter
from fastapi import Depends

from onyx.auth.users import current_admin_user
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(
    prefix="/admin/debug",
    tags=["debug"],
    dependencies=[Depends(current_admin_user)],
)

_start_time: float | None = None


def _get_process() -> psutil.Process:
    """Return a psutil.Process for the *current* PID.

    Lazily created and invalidated when PID changes (fork).
    """
    global _process, _process_pid
    pid = os.getpid()
    if _process is None or _process_pid != pid:
        _process = psutil.Process(pid)
        # Prime cpu_percent() so the first real call returns a
        # meaningful value instead of 0.0.
        _process.cpu_percent()
    _process_pid = pid
    return _process


_process: psutil.Process | None = None
_process_pid: int | None = None


def set_start_time() -> None:
    """Capture server startup time. Called from start_observability()."""
    global _start_time
    if _start_time is None:
        _start_time = time.monotonic()
        # Warm the process handle so cpu_percent() is primed.
        _get_process()


@router.get("/process-info")
def get_process_info() -> dict[str, Any]:
    """Return process-level resource info."""
    proc = _get_process()
    mem = proc.memory_info()
    uptime: float | None = (
        round(time.monotonic() - _start_time, 1) if _start_time is not None else None
    )
    info: dict[str, Any] = {
        "rss_bytes": mem.rss,
        "vms_bytes": mem.vms,
        "cpu_percent": proc.cpu_percent(),
        "num_threads": proc.num_threads(),
        "uptime_seconds": uptime,
    }
    # num_fds() is Linux-only; skip gracefully on macOS/Windows
    try:
        info["num_fds"] = proc.num_fds()
    except (AttributeError, psutil.Error):
        pass
    return info


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
    except (ImportError, RuntimeError, AttributeError):
        logger.warning("Failed to read postgres pool state", exc_info=True)
        result["postgres"]["error"] = "unable to read pool state"

    # Redis pools — uses private redis-py attributes (_in_use_connections, etc.)
    # because there is no public API for pool statistics.  Wrapped per-pool so
    # one failure doesn't block the other.
    # NOTE: RedisPool is a singleton — RedisPool() returns the existing instance.
    # NOTE: _in_use_connections, _available_connections, _created_connections are
    # private attrs on BlockingConnectionPool. If redis-py changes these in a
    # future version, the per-pool except block catches AttributeError gracefully.
    try:
        from redis import BlockingConnectionPool

        from onyx.redis.redis_pool import RedisPool

        pool_instance = RedisPool()
        # Replica pool always exists (defaults to same host as primary)
        for label, rpool in [
            ("primary", cast(BlockingConnectionPool, pool_instance._pool)),
            ("replica", cast(BlockingConnectionPool, pool_instance._replica_pool)),
        ]:
            try:
                result["redis"][label] = {
                    "in_use": len(rpool._in_use_connections),
                    "available": len(rpool._available_connections),
                    "max_connections": rpool.max_connections,
                    "created_connections": rpool._created_connections,
                }
            except (AttributeError, TypeError):
                logger.warning(
                    "Redis pool %s: unable to read internals — "
                    "redis-py private API may have changed",
                    label,
                    exc_info=True,
                )
                result["redis"][label] = {"error": "unable to read pool internals"}
    except (ImportError, RuntimeError, AttributeError):
        logger.warning("Failed to read redis pool state", exc_info=True)
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
