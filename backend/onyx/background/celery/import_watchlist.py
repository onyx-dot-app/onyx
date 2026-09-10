"""Heavy modules that Celery workers should not load at boot, plus a memory probe.

Shared by the `memory_report` inspect command, the worker import regression test
and `scripts/debugging/celery_import_report.py`. Keep this module stdlib-only so
importing it never changes what it measures.
"""

import os
from collections.abc import Iterable
from typing import Any

IMPORT_WATCHLIST: tuple[str, ...] = (
    # third party
    "litellm",
    "transformers",
    "torch",
    "openai",
    "braintrust",
    "exa_py",
    "playwright",
    "langchain_core",
    "chonkie",
    "tokenizers",
    "slack_sdk",
    "docx",
    "dns",
    "fastapi_users",
    "boto3",
    "opensearchpy",
    # first party
    "onyx.chat.process_message",
    "onyx.tools.built_in_tools",
    "onyx.indexing.indexing_pipeline",
    "onyx.connectors.factory",
    "onyx.evals.eval",
    "onyx.setup",
)


def loaded_watchlist_modules(module_names: Iterable[str]) -> list[str]:
    """Watchlist entries present in `module_names`, matched exactly or as a dotted prefix."""
    names = set(module_names)
    return [
        entry
        for entry in IMPORT_WATCHLIST
        if entry in names or any(name.startswith(entry + ".") for name in names)
    ]


def _read_proc_kb(path: str, keys: tuple[str, ...]) -> dict[str, int]:
    values: dict[str, int] = {}
    with open(path) as f:
        for line in f:
            key, _, rest = line.partition(":")
            if key in keys:
                values[key] = int(rest.split()[0])
    return values


def process_memory_snapshot() -> dict[str, Any]:
    """RSS and PSS in MB plus OS thread count for the current process.

    Reads /proc on Linux, falls back to psutil elsewhere (no PSS there).
    """
    try:
        status = _read_proc_kb("/proc/self/status", ("VmRSS", "Threads"))
        rollup = _read_proc_kb("/proc/self/smaps_rollup", ("Pss",))
        return {
            "source": "proc",
            "rss_mb": round(status["VmRSS"] / 1024, 1),
            "pss_mb": round(rollup["Pss"] / 1024, 1),
            # the Threads line is a plain count, not kB
            "os_threads": status["Threads"],
        }
    except (OSError, KeyError, ValueError):
        pass

    try:
        import psutil

        proc = psutil.Process(os.getpid())
        return {
            "source": "psutil",
            "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
            "pss_mb": None,
            "os_threads": proc.num_threads(),
        }
    except Exception:
        return {
            "source": "unavailable",
            "rss_mb": None,
            "pss_mb": None,
            "os_threads": None,
        }
