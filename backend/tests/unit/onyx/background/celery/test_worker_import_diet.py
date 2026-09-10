"""Guards what each Celery worker imports at boot.

Every worker process holds its boot-time imports for its whole life, so a
module-level import of a heavy package in any autodiscovered task module costs
memory in every deployment. Each worker is booted the way Celery boots it
(import the versioned app, then `app.loader.import_default_modules()`) in a
fresh interpreter, so EE and config state never leak into the pytest process.

`IMPORT_WATCHLIST` is the denylist. `_ALLOWED_WATCHLIST` records the entries a
worker still loads at boot; only ever shrink it. When this fails, make the new
import function-local (see `scripts/debugging/celery_import_report.py --who`).
"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from onyx.background.celery.import_watchlist import IMPORT_WATCHLIST

_BACKEND_DIR = Path(__file__).parents[5]
_REPORT_PREFIX = "__WORKER_BOOT_REPORT__"
_PROBE = f"""
import importlib, json, sys
from onyx.background.celery.import_watchlist import loaded_watchlist_modules

app = importlib.import_module("onyx.background.celery.versioned_apps." + sys.argv[1]).app
app.loader.import_default_modules()
print({_REPORT_PREFIX!r} + json.dumps({{
    "watchlist_loaded": loaded_watchlist_modules(sys.modules),
    "tasks": sorted(app.tasks),
    "modules": len(sys.modules),
}}))
"""

_BASELINE_APP_STAGE = {"fastapi_users", "boto3", "opensearchpy"}

_ALLOWED_WATCHLIST: dict[str, set[str]] = {
    "primary": _BASELINE_APP_STAGE
    | {
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
        "onyx.chat.process_message",
        "onyx.tools.built_in_tools",
        "onyx.indexing.indexing_pipeline",
        "onyx.connectors.factory",
        "onyx.evals.eval",
    },
    "light": _BASELINE_APP_STAGE
    | {
        "chonkie",
        "tokenizers",
        "slack_sdk",
        "onyx.indexing.indexing_pipeline",
        "onyx.connectors.factory",
    },
    "heavy": _BASELINE_APP_STAGE
    | {"tokenizers", "slack_sdk", "onyx.connectors.factory"},
    "docprocessing": _BASELINE_APP_STAGE
    | {
        "chonkie",
        "tokenizers",
        "onyx.indexing.indexing_pipeline",
        "onyx.connectors.factory",
    },
    "docfetching": _BASELINE_APP_STAGE
    | {
        "chonkie",
        "tokenizers",
        "onyx.indexing.indexing_pipeline",
        "onyx.connectors.factory",
    },
    "user_file_processing": _BASELINE_APP_STAGE
    | {"chonkie", "tokenizers", "onyx.indexing.indexing_pipeline"},
    "scheduled_tasks": _BASELINE_APP_STAGE | {"tokenizers", "docx"},
    "monitoring": _BASELINE_APP_STAGE
    | {
        "openai",
        "exa_py",
        "playwright",
        "langchain_core",
        "chonkie",
        "tokenizers",
        "slack_sdk",
        "onyx.tools.built_in_tools",
        "onyx.connectors.factory",
        "onyx.setup",
    },
    "beat": _BASELINE_APP_STAGE,
}

# One task per autodiscovered package, so moving an import or trimming an
# autodiscover list cannot silently unregister a task the worker consumes.
_MUST_REGISTER: dict[str, set[str]] = {
    "primary": {
        "check_for_connector_deletion_task",
        "docprocessing_task",
        "run_old_index_reclaim",
        "run_port_attempt",
        "eval_run_task",
        "connector_hierarchy_fetching_task",
        "connector_pruning_generator_task",
        "scheduled_tasks_run",
        "document_by_cc_pair_cleanup_task",
        "check_for_vespa_sync_task",
        "check_for_auto_llm_update",
        "process_single_user_file",
        "run_capability_checks",
        "hook_execution_log_cleanup_task",
        "connector_permission_sync_generator_task",
        "connector_external_group_sync_generator_task",
        "cloud_generate_beat_tasks",
        "perform_ttl_management_task",
        "generate_usage_report_task",
        "check_license_expiry_notifications",
        "reclaim_license",
        "export_logs_collect_task",
        "revalidate_sso_domains_task",
    },
    "light": {
        "document_by_cc_pair_cleanup_task",
        "check_for_vespa_sync_task",
        "check_for_connector_deletion_task",
        "run_old_index_reclaim",
        "cleanup_index_attempt",
        "migrate_chunks_from_vespa_to_opensearch_task",
        "connector_permission_sync_generator_task",
        "connector_external_group_sync_generator_task",
        "perform_ttl_management_task",
        "export_logs_collect_task",
    },
    "heavy": {
        "connector_pruning_generator_task",
        "cleanup_idle_sandboxes",
        "connector_hierarchy_fetching_task",
        "run_capability_checks",
        "connector_permission_sync_generator_task",
        "connector_external_group_sync_generator_task",
        "export_query_history_task",
        "export_logs_collect_task",
    },
    "docprocessing": {
        "docprocessing_task",
        "targeted_reindex_task",
        "run_port_attempt",
        "export_logs_collect_task",
    },
    "docfetching": {"connector_doc_fetching_task", "export_logs_collect_task"},
    "user_file_processing": {
        "process_single_user_file",
        "run_user_file_port_attempt",
        "export_logs_collect_task",
    },
    "scheduled_tasks": {"scheduled_tasks_run", "export_logs_collect_task"},
    "monitoring": {
        "monitor_celery_queues",
        "cloud_check_available_tenants",
        "export_logs_collect_task",
    },
    "beat": set(),
}

_WORKERS = sorted(_ALLOWED_WATCHLIST)


def _boot_worker(worker: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, worker],
        capture_output=True,
        text=True,
        timeout=180,
        env={"PYTHONPATH": str(_BACKEND_DIR)},
    )
    for line in reversed(result.stdout.splitlines()):
        if line.startswith(_REPORT_PREFIX):
            return json.loads(line[len(_REPORT_PREFIX) :])
    raise AssertionError(
        f"booting {worker} failed (exit {result.returncode}):\n{result.stderr[-4000:]}"
    )


@pytest.fixture(scope="module")
def boot_reports() -> dict[str, dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=len(_WORKERS)) as pool:
        return dict(zip(_WORKERS, pool.map(_boot_worker, _WORKERS), strict=True))


def test_allowlists_only_name_watchlist_modules() -> None:
    assert set(_ALLOWED_WATCHLIST) == set(_MUST_REGISTER)
    for worker, allowed in _ALLOWED_WATCHLIST.items():
        assert allowed <= set(IMPORT_WATCHLIST), worker


@pytest.mark.parametrize("worker", _WORKERS)
def test_worker_boot_imports_stay_off_watchlist(
    worker: str, boot_reports: dict[str, dict[str, Any]]
) -> None:
    loaded = set(boot_reports[worker]["watchlist_loaded"])
    unexpected = loaded - _ALLOWED_WATCHLIST[worker]
    assert not unexpected, (
        f"{worker} now imports {sorted(unexpected)} at boot; make the import "
        "function-local in the task module that pulls it in"
    )
    no_longer_loaded = _ALLOWED_WATCHLIST[worker] - loaded
    assert not no_longer_loaded, (
        f"{worker} no longer imports {sorted(no_longer_loaded)} at boot; "
        "remove them from _ALLOWED_WATCHLIST to lock in the saving"
    )


@pytest.mark.parametrize("worker", _WORKERS)
def test_worker_registers_its_tasks(
    worker: str, boot_reports: dict[str, dict[str, Any]]
) -> None:
    missing = _MUST_REGISTER[worker] - set(boot_reports[worker]["tasks"])
    assert not missing, f"{worker} no longer registers {sorted(missing)}"
