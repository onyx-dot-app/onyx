"""Prometheus metrics for code mode capacity in one API server process.

The sandbox worker pool, the dumped-program budget, the tool call thread budget
and the running cell budget are per process. The gauges of these budgets each
have a matching `_limit` gauge to compare against; they describe the pod and
have no tenant label. Counters of the use of this capacity carry a `tenant_id`
label, so that `rate()` gives each tenant's share. Other labels are closed
enums; no user labels.
"""

from typing import Literal

from prometheus_client import Counter, Gauge, Histogram

from onyx.tools.tool_implementations.code_mode.models import ClosedStatus
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

WorkerLossReason = Literal["crashed", "killed", "out_of_memory"]
SuspensionOutcome = Literal["dumped", "over_budget", "over_memory"]

SANDBOX_WORKERS_BUSY = Gauge(
    "onyx_code_mode_sandbox_workers_busy",
    "Sandbox worker processes checked out by programs.",
)
SANDBOX_WORKERS_LIMIT = Gauge(
    "onyx_code_mode_sandbox_workers_limit",
    "Sandbox worker processes the pool can start.",
)
PROGRAMS_WAITING_FOR_WORKER = Gauge(
    "onyx_code_mode_programs_waiting_for_worker",
    "Programs waiting to check out a sandbox worker.",
)
SANDBOX_BUSY_REJECTIONS = Counter(
    "onyx_code_mode_sandbox_busy_rejections_total",
    "New programs that got no sandbox worker in time and did not run, by tenant.",
    ["tenant_id"],
)
SANDBOX_WORKER_SECONDS = Counter(
    "onyx_code_mode_sandbox_worker_seconds_total",
    "Seconds that programs held a sandbox worker, by tenant.",
    ["tenant_id"],
)
SANDBOX_WORKERS_LOST = Counter(
    "onyx_code_mode_sandbox_workers_lost_total",
    "Sandbox workers that the pool replaces: crashed, killed on Stop or a "
    "deadline, or out of memory while dumping a program.",
    ["reason"],
)
SUSPENDED_BYTES = Gauge(
    "onyx_code_mode_suspended_bytes",
    "Bytes of dumped programs held in the process while they wait for tool calls.",
)
SUSPENDED_BYTES_LIMIT = Gauge(
    "onyx_code_mode_suspended_bytes_limit",
    "Budget of dumped program bytes held in the process.",
)
SUSPENSIONS = Counter(
    "onyx_code_mode_suspensions_total",
    "Waiting programs dumped to free their worker, or kept on it: over the dump "
    "byte budget, or with too much memory in the worker to dump.",
    ["outcome"],
)
TOOL_CALL_THREADS_IN_USE = Gauge(
    "onyx_code_mode_tool_call_threads_in_use",
    "Threads running tool calls of programs.",
)
TOOL_CALL_THREADS_HELD_AFTER_END = Gauge(
    "onyx_code_mode_tool_call_threads_held_after_end",
    "Tool call threads still held by calls whose program ended: calls that "
    "ignore cancellation, such as hung tools.",
)
TOOL_CALL_THREADS_LIMIT = Gauge(
    "onyx_code_mode_tool_call_threads_limit",
    "Budget of threads for tool calls of programs.",
)
CELLS_RUNNING = Gauge(
    "onyx_code_mode_cells_running",
    "Cells whose program has not ended, each with a driver thread.",
)
CELLS_LIMIT = Gauge(
    "onyx_code_mode_cells_limit",
    "Cells whose program has not ended that the process allows.",
)
CELL_BUSY_REJECTIONS = Counter(
    "onyx_code_mode_cell_busy_rejections_total",
    "New cells refused because the process had its limit of running cells, by tenant.",
    ["tenant_id"],
)
CELL_SECONDS = Counter(
    "onyx_code_mode_cell_seconds_total",
    "Seconds that programs held a running-cell slot, by tenant.",
    ["tenant_id"],
)
PROGRAMS = Counter(
    "onyx_code_mode_programs_total",
    "Programs that ended, by tenant and status.",
    ["tenant_id", "status"],
)
PROGRAM_DURATION = Histogram(
    "onyx_code_mode_program_duration_seconds",
    "Time from a program's start to its end, waiting for tool calls included.",
    # Dense from 2.5 s to 10 s, where the p95 of typical programs falls.
    buckets=(
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        3.0,
        4.0,
        5.0,
        6.0,
        8.0,
        10.0,
        30.0,
        60.0,
        120.0,
        300.0,
        900.0,
    ),
)
PROGRAM_START_DURATION = Histogram(
    "onyx_code_mode_program_start_duration_seconds",
    "Time to type-check a program and run it to its first wait or end.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def set_code_mode_limits(
    *,
    sandbox_workers: int,
    suspended_bytes: int,
    tool_call_threads: int,
    running_cells: int,
) -> None:
    SANDBOX_WORKERS_LIMIT.set(sandbox_workers)
    SUSPENDED_BYTES_LIMIT.set(suspended_bytes)
    TOOL_CALL_THREADS_LIMIT.set(tool_call_threads)
    CELLS_LIMIT.set(running_cells)


def observe_program_end(
    tenant_id: str, status: ClosedStatus, duration_seconds: float
) -> None:
    PROGRAMS.labels(tenant_id=tenant_id, status=status).inc()
    PROGRAM_DURATION.observe(duration_seconds)


def count_worker_lost(reason: WorkerLossReason) -> None:
    SANDBOX_WORKERS_LOST.labels(reason=reason).inc()


def count_suspension(outcome: SuspensionOutcome) -> None:
    SUSPENSIONS.labels(outcome=outcome).inc()


def current_tenant_id() -> str:
    """The `tenant_id` label of the current request."""
    return CURRENT_TENANT_ID_CONTEXTVAR.get() or "unknown"
