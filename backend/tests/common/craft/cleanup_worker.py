"""Drive the deployed cleanup worker and wait for its actual completion."""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

import pytest
from kubernetes import client

from onyx.background.celery.apps.client import celery_app
from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask
from onyx.server.features.build.configs import (
    SANDBOX_BACKEND,
    SANDBOX_RESOURCE_GRACE_SECONDS,
    SandboxBackend,
)

APP_NAMESPACE = os.environ.get("HELM_RELEASE_NAMESPACE", "onyx")


def require_isolated_cleanup_deployment() -> None:
    if (
        SANDBOX_BACKEND == SandboxBackend.KUBERNETES
        and os.environ.get("SANDBOX_TEST_ISOLATED_DEPLOYMENT") != "true"
    ):
        raise pytest.UsageError(
            "Cleanup fault tests require SANDBOX_TEST_ISOLATED_DEPLOYMENT=true. "
            "Use the dedicated Kubernetes CI deployment, not shared Craft Dev."
        )


@pytest.fixture
def isolated_cleanup_deployment(k8s_client: client.CoreV1Api) -> None:
    require_isolated_cleanup_deployment()
    namespace = k8s_client.read_namespace(APP_NAMESPACE, _request_timeout=10)
    run_id = os.environ.get("SANDBOX_TEST_RUN_ID")
    assert run_id, "SANDBOX_TEST_RUN_ID must identify the disposable CI deployment"
    assert (namespace.metadata.labels or {}).get(
        "onyx.app/cleanup-test-run"
    ) == run_id, "The target namespace does not belong to this cleanup test run"


# The per-tenant sweep expires stale provisioning; the reconciler then removes
# runtime resources that no database row justifies.
_CLEANUP_TASKS: tuple[tuple[str, dict[str, str]], ...] = (
    (OnyxCeleryTask.CLEANUP_IDLE_SANDBOXES, {"tenant_id": "public"}),
    (OnyxCeleryTask.RECONCILE_SANDBOX_RUNTIMES, {}),
)


def _send_cleanup(task_name: str, kwargs: dict[str, str]) -> str:
    task_id = str(uuid4())
    celery_app.send_task(
        task_name,
        task_id=task_id,
        kwargs=kwargs,
        queue=OnyxCeleryQueues.SANDBOX,
        expires=120,
    )
    return task_id


def run_cleanup(
    core: client.CoreV1Api, expected_state: Literal["SUCCESS", "FAILURE"] = "SUCCESS"
) -> None:
    require_isolated_cleanup_deployment()
    for task_name, kwargs in _CLEANUP_TASKS:
        _run_cleanup_task(core, task_name, kwargs, expected_state)


def _run_cleanup_task(
    core: client.CoreV1Api,
    task_name: str,
    kwargs: dict[str, str],
    expected_state: Literal["SUCCESS", "FAILURE"],
) -> None:
    task_id = _send_cleanup(task_name, kwargs)
    marker = f"(ID: {task_id}) completed with state:"
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        for pod in core.list_namespaced_pod(
            APP_NAMESPACE, label_selector="app=celery-worker-heavy", _request_timeout=10
        ).items:
            logs = core.read_namespaced_pod_log(
                pod.metadata.name,
                APP_NAMESPACE,
                since_seconds=180,
                tail_lines=10000,
                _request_timeout=10,
            )
            lines = logs.splitlines()
            completed = next((line for line in lines if marker in line), None)
            if completed is None:
                continue
            if any(
                task_id in line and "lock not acquired, skipping" in line
                for line in lines
            ):
                task_id = _send_cleanup(task_name, kwargs)
                marker = f"(ID: {task_id}) completed with state:"
                break
            assert f"{marker} {expected_state}" in completed, completed
            return
        time.sleep(0.5)
    pytest.fail(
        f"Cleanup task {task_id} did not complete. "
        "The test deployment's heavy worker must use DEBUG logging."
    )


def wait_for_resource_grace(
    core: client.CoreV1Api, pod_name: str, namespace: str
) -> None:
    pod = core.read_namespaced_pod(pod_name, namespace, _request_timeout=10)
    eligible_at = pod.metadata.creation_timestamp + timedelta(
        seconds=SANDBOX_RESOURCE_GRACE_SECONDS + 2
    )
    while (remaining := (eligible_at - datetime.now(timezone.utc)).total_seconds()) > 0:
        time.sleep(min(2, remaining))
