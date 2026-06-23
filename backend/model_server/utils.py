import asyncio
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from functools import wraps
from pathlib import Path
from typing import Any
from typing import cast
from typing import TypeVar

import torch

from model_server.constants import GPUStatus
from onyx.utils.logger import setup_logger

logger = setup_logger()

F = TypeVar("F", bound=Callable)
FG = TypeVar("FG", bound=Callable[..., Generator | Iterator])


def simple_log_function_time(
    func_name: str | None = None,
    debug_only: bool = False,
    include_args: bool = False,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def wrapped_async_func(*args: Any, **kwargs: Any) -> Any:
                start_time = time.time()
                result = await func(*args, **kwargs)
                elapsed_time_str = str(time.time() - start_time)
                log_name = func_name or func.__name__
                args_str = f" args={args} kwargs={kwargs}" if include_args else ""
                final_log = f"{log_name}{args_str} took {elapsed_time_str} seconds"
                if debug_only:
                    logger.debug(final_log)
                else:
                    logger.notice(final_log)
                return result

            return cast(F, wrapped_async_func)
        else:

            @wraps(func)
            def wrapped_sync_func(*args: Any, **kwargs: Any) -> Any:
                start_time = time.time()
                result = func(*args, **kwargs)
                elapsed_time_str = str(time.time() - start_time)
                log_name = func_name or func.__name__
                args_str = f" args={args} kwargs={kwargs}" if include_args else ""
                final_log = f"{log_name}{args_str} took {elapsed_time_str} seconds"
                if debug_only:
                    logger.debug(final_log)
                else:
                    logger.notice(final_log)
                return result

            return cast(F, wrapped_sync_func)

    return decorator


def get_gpu_type() -> str:
    if torch.cuda.is_available():
        return GPUStatus.CUDA
    if torch.backends.mps.is_available():
        return GPUStatus.MAC_MPS

    return GPUStatus.NONE


CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
CGROUP_V1_CPU_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
CGROUP_V1_CPU_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def get_cgroup_cpu_limit(
    v2_cpu_max: Path = CGROUP_V2_CPU_MAX,
    v1_cpu_quota: Path = CGROUP_V1_CPU_QUOTA,
    v1_cpu_period: Path = CGROUP_V1_CPU_PERIOD,
) -> int | None:
    """Number of CPU cores available to this container per its cgroup CFS quota.

    torch and the underlying OpenMP/BLAS runtimes size their thread pools from the
    host's core count and are unaware of cgroup limits. On a large node a CPU-limited
    container therefore spins up far more threads than its quota allows, which thrashes
    and gets CFS-throttled. We read the quota directly so callers can cap thread counts
    to the budget the container actually has.

    Returns None when no quota is set (unlimited) or the cgroup files are unavailable
    or unreadable. Quotas are floored to whole cores so the cap never exceeds the
    container's actual CPU budget.
    """
    # cgroup v2: single file formatted as "<quota> <period>"; "max" means unlimited.
    # When the v2 file is present it is authoritative: we never fall back to v1, since a
    # hybrid host can carry stale v1 quota files that don't reflect the real limit.
    try:
        quota_str, period_str = v2_cpu_max.read_text().split()
        if quota_str == "max":
            return None
        period = int(period_str)
        if period > 0:
            return max(1, int(quota_str) // period)
        return None
    except FileNotFoundError:
        pass  # not a cgroup v2 host; fall back to v1
    except (OSError, ValueError) as e:
        # v2 is present but unreadable/malformed; it remains authoritative, so do not
        # trust v1 — report undetectable rather than apply a possibly-stale quota.
        logger.debug("Could not parse cgroup v2 cpu.max (%s): %s", v2_cpu_max, e)
        return None

    # cgroup v1: separate quota/period files; quota <= 0 means unlimited.
    try:
        quota = int(v1_cpu_quota.read_text())
        period = int(v1_cpu_period.read_text())
        if quota > 0 and period > 0:
            return max(1, quota // period)
    except FileNotFoundError:
        pass  # no cgroup cpu controller available; treat as unlimited
    except (OSError, ValueError) as e:
        logger.debug("Could not parse cgroup v1 cpu quota/period: %s", e)

    return None
