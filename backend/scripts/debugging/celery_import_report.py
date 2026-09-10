"""Report what each Celery worker imports at boot and what it costs.

For every selected worker this spawns a fresh interpreter that imports the
versioned app, then runs `app.loader.import_default_modules()` exactly like the
worker does at startup. It prints RSS/PSS and module counts after each stage,
the marginal cost of each autodiscovered task package, the loaded watchlist
modules and the registered task count.

Usage (from backend/):
  python scripts/debugging/celery_import_report.py                  # all workers
  python scripts/debugging/celery_import_report.py light --packages # per-package cost
  python scripts/debugging/celery_import_report.py primary --who braintrust
  python scripts/debugging/celery_import_report.py --json

`--who MODULE` prints the chain of modules that first imported MODULE. Chains
end at the autodiscovered package, which Celery imports with importlib.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKERS = (
    "primary",
    "light",
    "heavy",
    "docprocessing",
    "docfetching",
    "user_file_processing",
    "scheduled_tasks",
    "monitoring",
    "beat",
)
_REPORT_PREFIX = "__CELERY_IMPORT_REPORT__"


def _install_import_tracker(importers: dict[str, str]) -> None:
    import builtins
    import importlib.util

    original_import = builtins.__import__

    def tracking_import(
        name: str,
        globals: dict[str, Any] | None = None,  # noqa: A002
        locals: dict[str, Any] | None = None,  # noqa: A002
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        importer = (globals or {}).get("__name__", "?")
        try:
            full_name = (
                importlib.util.resolve_name("." * level + name, globals["__package__"])
                if level and globals
                else name
            )
        except (ImportError, KeyError, ValueError):
            full_name = name
        candidates = [full_name] + [f"{full_name}.{item}" for item in fromlist or ()]
        for candidate in candidates:
            if candidate not in sys.modules and candidate not in importers:
                importers[candidate] = importer
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = tracking_import  # ty: ignore[invalid-assignment]


def _import_chain(importers: dict[str, str], target: str) -> list[str]:
    start = next(
        (name for name in importers if name == target or name.startswith(target + ".")),
        None,
    )
    if start is None:
        return []
    chain = [start]
    while chain[-1] in importers and len(chain) < 40:
        parent = importers[chain[-1]]
        if parent in chain:
            break
        chain.append(parent)
    return chain


def _run_child(worker: str, who: str | None) -> None:
    import importlib

    import celery.loaders.base as celery_loader_base

    from onyx.background.celery.import_watchlist import (
        loaded_watchlist_modules,
        process_memory_snapshot,
    )

    importers: dict[str, str] = {}
    if who:
        _install_import_tracker(importers)

    report: dict[str, Any] = {"worker": worker}
    app = importlib.import_module(f"onyx.background.celery.versioned_apps.{worker}").app
    report["app_stage"] = {**process_memory_snapshot(), "modules": len(sys.modules)}

    packages: list[dict[str, Any]] = []
    original_find = celery_loader_base.find_related_module  # ty: ignore[unresolved-attribute]

    def measured_find(package: str, related_name: str) -> Any:
        before_rss = process_memory_snapshot()["rss_mb"] or 0.0
        before_modules = len(sys.modules)
        try:
            return original_find(package, related_name)
        finally:
            packages.append(
                {
                    "package": package,
                    "delta_rss_mb": round(
                        (process_memory_snapshot()["rss_mb"] or 0.0) - before_rss, 1
                    ),
                    "new_modules": len(sys.modules) - before_modules,
                }
            )

    celery_loader_base.find_related_module = measured_find  # ty: ignore[unresolved-attribute]
    app.loader.import_default_modules()
    celery_loader_base.find_related_module = original_find  # ty: ignore[unresolved-attribute]

    report["boot_stage"] = {**process_memory_snapshot(), "modules": len(sys.modules)}
    report["packages"] = packages
    report["registered_tasks"] = len(
        [name for name in app.tasks if not name.startswith("celery.")]
    )
    report["watchlist_loaded"] = loaded_watchlist_modules(sys.modules)
    if who:
        report["who"] = {"module": who, "chain": _import_chain(importers, who)}
    print(_REPORT_PREFIX + json.dumps(report))


def _spawn_child(worker: str, who: str | None) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(BACKEND_DIR), env.get("PYTHONPATH")) if p
    )
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child", worker]
    if who:
        cmd += ["--who", who]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=BACKEND_DIR, env=env, timeout=300
    )
    for line in reversed(result.stdout.splitlines()):
        if line.startswith(_REPORT_PREFIX):
            return json.loads(line[len(_REPORT_PREFIX) :])
    raise RuntimeError(
        f"{worker}: child exited {result.returncode} without a report\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-4000:]}"
    )


def _print_reports(reports: list[dict[str, Any]], show_packages: bool) -> None:
    header = (
        f"{'worker':22s} {'app_rss':>8s} {'app_mods':>8s} {'boot_rss':>8s} "
        f"{'boot_pss':>8s} {'boot_mods':>9s} {'tasks':>5s}  watchlist"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        app, boot = r["app_stage"], r["boot_stage"]
        print(
            f"{r['worker']:22s} {app['rss_mb']:8} {app['modules']:8d} "
            f"{boot['rss_mb']:8} {boot['pss_mb']:8} {boot['modules']:9d} "
            f"{r['registered_tasks']:5d}  {', '.join(r['watchlist_loaded']) or '-'}"
        )
    print(
        f"\nsum boot_rss: {sum(r['boot_stage']['rss_mb'] or 0 for r in reports):.0f} MB"
    )

    for r in reports:
        if show_packages:
            print(f"\n{r['worker']}: marginal cost per autodiscovered package")
            for p in r["packages"]:
                print(
                    f"  {p['package']:65s} {p['delta_rss_mb']:7.1f} MB "
                    f"{p['new_modules']:5d} modules"
                )
        if "who" in r:
            chain = r["who"]["chain"]
            print(f"\n{r['worker']}: first import chain for {r['who']['module']}")
            print("  " + (" <- ".join(chain) if chain else "(not imported)"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workers", nargs="*", choices=[[], *WORKERS], default=[])
    parser.add_argument("--packages", action="store_true", help="per-package cost")
    parser.add_argument("--who", help="print the first import chain for a module")
    parser.add_argument("--json", action="store_true", help="print raw JSON reports")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child:
        _run_child(args.child, args.who)
        return

    reports = [_spawn_child(w, args.who) for w in (args.workers or WORKERS)]
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        _print_reports(reports, args.packages)


if __name__ == "__main__":
    main()
