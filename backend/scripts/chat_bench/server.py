"""Starts the real API server for the chat turn benchmark, with counters.

The counters are added from outside: no product code knows about them. The
route /_bench/stats returns their totals, so the benchmark can take the
difference over a set of turns.
"""

import os
import re
import resource
import sys
import threading
import time
from collections import Counter
from typing import Any

import psutil
import redis
import uvicorn
from sqlalchemy import event
from sqlalchemy.engine import Engine

_lock = threading.Lock()
_counts: dict[str, int] = {
    "sql_statements": 0,
    "sql_commits": 0,
    "sql_rollbacks": 0,
    "sql_connections_checked_out": 0,
    "cache_commands": 0,
    "threads_started": 0,
}


# What the statements and cache commands are, for the breakdown route.
_sql_statements: Counter[str] = Counter()
_cache_commands: Counter[str] = Counter()
# Collapsed stacks of all threads, sampled when CHAT_BENCH_SAMPLE_MS is set.
_stack_samples: Counter[str] = Counter()
_WHITESPACE = re.compile(r"\s+")
_IN_LIST = re.compile(r"IN \([^)]*\)")


def _add(key: str, amount: int = 1) -> None:
    with _lock:
        _counts[key] += amount


def _install_counters() -> None:
    @event.listens_for(Engine, "before_cursor_execute")
    def _statement(
        _conn: Any, _cursor: Any, statement: str, *_args: Any, **_kwargs: Any
    ) -> None:
        shape = _IN_LIST.sub("IN (...)", _WHITESPACE.sub(" ", statement))[:160]
        with _lock:
            _counts["sql_statements"] += 1
            _sql_statements[shape] += 1

    @event.listens_for(Engine, "commit")
    def _commit(*_args: Any, **_kwargs: Any) -> None:
        _add("sql_commits")

    @event.listens_for(Engine, "rollback")
    def _rollback(*_args: Any, **_kwargs: Any) -> None:
        _add("sql_rollbacks")

    @event.listens_for(Engine, "checkout")
    def _checkout(*_args: Any, **_kwargs: Any) -> None:
        _add("sql_connections_checked_out")

    execute_command = redis.Redis.execute_command

    def counted_command(self: Any, *args: Any, **kwargs: Any) -> Any:
        with _lock:
            _counts["cache_commands"] += 1
            _cache_commands[str(args[0]) if args else "?"] += 1
        return execute_command(self, *args, **kwargs)

    redis.Redis.execute_command = counted_command

    pipeline_execute = redis.client.Pipeline.execute

    def counted_pipeline(self: Any, *args: Any, **kwargs: Any) -> Any:
        with _lock:
            _counts["cache_commands"] += max(len(self.command_stack), 1)
            _cache_commands["pipeline"] += 1
        return pipeline_execute(self, *args, **kwargs)

    redis.client.Pipeline.execute = counted_pipeline

    thread_start = threading.Thread.start

    def counted_start(self: threading.Thread) -> None:
        _add("threads_started")
        thread_start(self)

    threading.Thread.start = counted_start


def _sample_stacks(interval_s: float) -> None:
    """A sampling profiler: cProfile cannot follow the threads of a turn."""
    own = threading.get_ident()
    while True:
        time.sleep(interval_s)
        for ident, frame in sys._current_frames().items():
            if ident == own:
                continue
            names: list[str] = []
            current: Any = frame
            while current is not None and len(names) < 60:
                code = current.f_code
                names.append(f"{os.path.basename(code.co_filename)}:{code.co_name}")
                current = current.f_back
            with _lock:
                _stack_samples[";".join(reversed(names))] += 1


def main() -> None:
    _install_counters()
    # After the counters: the import builds the engine and the app.
    from onyx.main import app as get_application

    app = get_application()

    process = psutil.Process()

    @app.get("/_bench/stats")
    def stats() -> dict[str, float]:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        with _lock:
            counts = dict(_counts)
        return {
            **counts,
            "cpu_user_seconds": usage.ru_utime,
            "cpu_system_seconds": usage.ru_stime,
            "rss_mb": process.memory_info().rss / 1e6,
            "threads_alive": threading.active_count(),
        }

    @app.get("/_bench/breakdown")
    def breakdown() -> dict[str, dict[str, int]]:
        with _lock:
            return {
                "sql_statements": dict(_sql_statements),
                "cache_commands": dict(_cache_commands),
                "stack_samples": dict(_stack_samples),
            }

    sample_ms = os.environ.get("CHAT_BENCH_SAMPLE_MS")
    if sample_ms:
        threading.Thread(
            target=_sample_stacks, args=(float(sample_ms) / 1000,), daemon=True
        ).start()

    uvicorn.run(
        app,
        host=os.environ.get("CHAT_BENCH_HOST", "127.0.0.1"),
        port=int(sys.argv[1]),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
