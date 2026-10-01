"""Resource reads run only in the sender worker or isolated collector."""

import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

if TYPE_CHECKING:
    from onyx.utils.fleet_telemetry import BoundedTelemetry

_last_cpu: tuple[float, float] | None = None


def _number(path: str) -> int | None:
    try:
        raw = Path(path).read_text().strip()
        value = int(raw)
        return value if 0 < value < 1 << 60 else None
    except (OSError, ValueError):
        return None


def collect_process_resource(client: "BoundedTelemetry") -> None:
    global _last_cpu
    try:
        process = psutil.Process()
        memory = _number("/sys/fs/cgroup/memory.current") or process.memory_info().rss
        memory_limit = _number("/sys/fs/cgroup/memory.max")
        if memory_limit is None:
            memory_limit = _number("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        cpu = process.cpu_times()
        cpu_seconds = cpu.user + cpu.system
        throttled = None
        quota = None
        try:
            stats = dict(
                line.split()
                for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines()
            )
            cpu_seconds = int(stats["usage_usec"]) / 1e6
            throttled = int(stats.get("throttled_usec", "0")) / 1e6
            maximum, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
            quota = int(maximum) / int(period) if maximum != "max" else None
        except (OSError, ValueError, KeyError):
            pass
        now = time.monotonic()
        used_cores = (
            max(0.0, (cpu_seconds - _last_cpu[0]) / (now - _last_cpu[1]))
            if _last_cpu and now > _last_cpu[1]
            else None
        )
        _last_cpu = (cpu_seconds, now)
        disk = shutil.disk_usage(os.environ.get("ONYX_TELEMETRY_DISK_MOUNT", "/"))
        client.emit(
            "resource",
            {
                "service_instance_id": client.fingerprint(
                    str(os.getpid()) + ":" + os.uname().nodename
                ),
                "memory_bytes": memory,
                "memory_limit_bytes": memory_limit,
                "disk_bytes": disk.used,
                "disk_limit_bytes": disk.total,
                "cpu_cores": used_cores,
                "cpu_limit_cores": quota,
                "cpu_throttled_seconds": throttled,
                "shared": True,
            },
        )
    except Exception:
        pass
