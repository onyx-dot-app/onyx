"""Prometheus metrics for code mode capacity in one API server process.

The sandbox worker pool, the dumped-program budget and the tool call thread
budget are per process. The gauges of these budgets each have a matching
`_limit` gauge to compare against. Labels are closed enums; no tenant or user
labels.
"""

from typing import Literal

from prometheus_client import Counter, Gauge, Histogram

WorkerLossReason = Literal["crashed", "killed"]
SuspensionOutcome = Literal["dumped", "over_budget"]

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
    "New programs that got no sandbox worker in time and did not run.",
)
SANDBOX_WORKERS_LOST = Counter(
    "onyx_code_mode_sandbox_workers_lost_total",
    "Sandbox workers that the pool replaces: crashed, or killed on Stop or a deadline.",
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
    "Waiting programs dumped to free their worker, or kept on it over the budget.",
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
PROGRAM_START_DURATION = Histogram(
    "onyx_code_mode_program_start_duration_seconds",
    "Time to type-check a program and run it to its first wait or end.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def set_code_mode_limits(
    *, sandbox_workers: int, suspended_bytes: int, tool_call_threads: int
) -> None:
    SANDBOX_WORKERS_LIMIT.set(sandbox_workers)
    SUSPENDED_BYTES_LIMIT.set(suspended_bytes)
    TOOL_CALL_THREADS_LIMIT.set(tool_call_threads)


def count_worker_lost(reason: WorkerLossReason) -> None:
    SANDBOX_WORKERS_LOST.labels(reason=reason).inc()


def count_suspension(outcome: SuspensionOutcome) -> None:
    SUSPENSIONS.labels(outcome=outcome).inc()
