"""Unit tests for the log export's Kubernetes API collector: which streams it
reads, how it caps them, and how it reports failures, against a fake API."""

import io
import json
import zipfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from ee.onyx.server.log_export import kubernetes_collection
from ee.onyx.server.log_export.kubernetes_collection import (
    EVENTS_FILE_NAME,
    PODS_FILE_NAME,
    build_kubernetes_log_zip,
    collect_kubernetes_logs_into_file_store,
)
from ee.onyx.server.log_export.models import (
    LogExportReceipt,
    LogExportReceiptStatus,
)

_NAMESPACE = "onyx"
_API_POD = "onyx-api-server-7d9f8-abcde"
_DOCPROCESSING_POD = "onyx-celery-worker-docprocessing-95f84-tt2fg"
_RELEASE_LABELS = {
    "app.kubernetes.io/name": "onyx",
    "app.kubernetes.io/instance": "onyx",
}
_T0 = datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)


def _pod(name: str, component: str, restart_count: int = 0) -> client.V1Pod:
    last_state = (
        client.V1ContainerState(
            terminated=client.V1ContainerStateTerminated(
                exit_code=137, reason="OOMKilled", started_at=_T0, finished_at=_T0
            )
        )
        if restart_count
        else None
    )
    return client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name,
            labels={**_RELEASE_LABELS, "app": component},
            owner_references=[
                client.V1OwnerReference(
                    api_version="apps/v1",
                    kind="ReplicaSet",
                    name=name.rsplit("-", 1)[0],
                    uid="uid",
                )
            ],
        ),
        spec=client.V1PodSpec(containers=[], node_name="node-1"),
        status=client.V1PodStatus(
            phase="Running",
            container_statuses=[
                client.V1ContainerStatus(
                    name=component,
                    image="onyx",
                    image_id="onyx",
                    ready=True,
                    restart_count=restart_count,
                    state=client.V1ContainerState(
                        running=client.V1ContainerStateRunning(started_at=_T0)
                    ),
                    last_state=last_state,
                )
            ],
        ),
    )


def _event(object_name: str, reason: str, message: str) -> client.CoreV1Event:
    return client.CoreV1Event(
        metadata=client.V1ObjectMeta(name=f"{object_name}.1"),
        involved_object=client.V1ObjectReference(kind="Pod", name=object_name),
        reason=reason,
        message=message,
        type="Warning",
        count=1,
        last_timestamp=_T0,
    )


class _FakeLogResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def stream(self, amt: int) -> Iterator[bytes]:
        for start in range(0, len(self._data), amt):
            yield self._data[start : start + amt]

    def release_conn(self) -> None:
        pass


class _FakeCoreV1Api(client.CoreV1Api):
    """Serves fixed pods, logs, and events; ignores ``limit_bytes`` so the
    collector's own byte bound is exercised."""

    def __init__(
        self,
        pods: list[client.V1Pod],
        logs: dict[tuple[str, bool], bytes],
        events: list[client.CoreV1Event],
        read_pod_error: ApiException | None = None,
    ) -> None:
        self._pods = pods
        self._logs = logs
        self._events = events
        self._read_pod_error = read_pod_error
        self.label_selectors: list[str] = []

    def read_namespaced_pod(self, name: str, namespace: str, **_: Any) -> Any:
        assert namespace == _NAMESPACE
        if self._read_pod_error is not None:
            raise self._read_pod_error
        return next(pod for pod in self._pods if pod.metadata.name == name)

    def list_namespaced_pod(self, namespace: str, **kwargs: Any) -> Any:
        assert namespace == _NAMESPACE
        self.label_selectors.append(kwargs["label_selector"])
        return client.V1PodList(items=self._pods)

    def read_namespaced_pod_log(self, name: str, namespace: str, **kwargs: Any) -> Any:
        assert namespace == _NAMESPACE
        key = (name, bool(kwargs["previous"]))
        if key not in self._logs:
            raise ApiException(status=400, reason="Bad Request")
        return _FakeLogResponse(self._logs[key])

    def list_namespaced_event(self, namespace: str, **_: Any) -> Any:
        assert namespace == _NAMESPACE
        return client.CoreV1EventList(items=self._events)


def _read_zip(built_buffer: Any) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(built_buffer.read())) as zip_file:
        return {name: zip_file.read(name) for name in zip_file.namelist()}


def test_restarted_container_collects_previous_log_and_termination() -> None:
    # Precondition.
    # The docprocessing container was OOM-killed once; its previous instance
    # holds the crash. Events exist for it, for a replaced pod of the same
    # Deployment, and for an unrelated workload.
    pods = [
        _pod(_API_POD, "api-server"),
        _pod(_DOCPROCESSING_POD, "celery-worker-docprocessing", restart_count=1),
    ]
    api = _FakeCoreV1Api(
        pods=pods,
        logs={
            (_API_POD, False): b"api line\n",
            (_DOCPROCESSING_POD, False): b"current line\n",
            (_DOCPROCESSING_POD, True): b"crash line\n",
        },
        events=[
            _event(_DOCPROCESSING_POD, "BackOff", "restarting failed container"),
            _event("onyx-celery-worker-docprocessing-95f84-old11", "Evicted", "memory"),
            _event("unrelated-db-0", "Pulled", "pulled image"),
        ],
    )

    # Under test.
    built = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, 30.0)

    # Postcondition.
    # Both instances of the restarted container are collected, the pods are
    # selected by the release labels, and only Onyx events are kept.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert built.log_file_count == 3
    assert files[f"logs/{_DOCPROCESSING_POD}/celery-worker-docprocessing.log"] == (
        b"current line\n"
    )
    assert files[
        f"logs/{_DOCPROCESSING_POD}/celery-worker-docprocessing.previous.log"
    ] == (b"crash line\n")
    assert api.label_selectors == [
        "app.kubernetes.io/name=onyx,app.kubernetes.io/instance=onyx"
    ]
    pod_summaries = json.loads(files[PODS_FILE_NAME])
    docprocessing = next(
        pod for pod in pod_summaries if pod["name"] == _DOCPROCESSING_POD
    )
    assert docprocessing["component"] == "celery-worker-docprocessing"
    assert docprocessing["containers"][0]["restart_count"] == 1
    assert docprocessing["containers"][0]["last_terminated"]["reason"] == "OOMKilled"
    events = files[EVENTS_FILE_NAME].decode()
    assert "BackOff" in events
    assert "Evicted" in events
    assert "unrelated-db-0" not in events


def test_stream_and_total_byte_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    # Precondition.
    # Each log is larger than the per-stream cap, and two capped logs exceed
    # the total cap.
    monkeypatch.setattr(
        kubernetes_collection, "LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM", 10
    )
    monkeypatch.setattr(
        kubernetes_collection, "LOG_EXPORT_KUBERNETES_MAX_TOTAL_BYTES", 15
    )
    pods = [
        _pod(_API_POD, "api-server"),
        _pod(_DOCPROCESSING_POD, "celery-worker-docprocessing"),
    ]
    api = _FakeCoreV1Api(
        pods=pods,
        logs={(_API_POD, False): b"a" * 100, (_DOCPROCESSING_POD, False): b"b" * 100},
        events=[],
    )

    # Under test.
    built = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, 30.0)

    # Postcondition.
    # The first log is cut to the stream cap; the second is left out and the
    # README says why.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert built.log_file_count == 1
    assert files[f"logs/{_API_POD}/api-server.log"] == b"a" * 10
    readme = files["README.txt"].decode()
    assert (
        f"logs/{_DOCPROCESSING_POD}/celery-worker-docprocessing.log: "
        "total byte cap reached"
    ) in readme


def test_missing_rbac_writes_failed_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Precondition.
    # The service account may not read pods.
    namespace_file = tmp_path / "namespace"
    namespace_file.write_text(_NAMESPACE)
    monkeypatch.setattr(
        kubernetes_collection, "SERVICE_ACCOUNT_NAMESPACE_FILE", namespace_file
    )
    monkeypatch.setattr(
        kubernetes_collection,
        "build_core_v1_api",
        lambda: _FakeCoreV1Api(
            pods=[],
            logs={},
            events=[],
            read_pod_error=ApiException(status=403, reason="Forbidden"),
        ),
    )
    saved_receipts: list[LogExportReceipt] = []
    monkeypatch.setattr(kubernetes_collection, "save_receipt", saved_receipts.append)

    def _fail_save_piece(*_: object) -> None:
        raise AssertionError("no piece is uploaded when collection fails")

    monkeypatch.setattr(kubernetes_collection, "save_piece", _fail_save_piece)

    # Under test.
    receipt = collect_kubernetes_logs_into_file_store(
        export_id="export", deadline=datetime.now(tz=timezone.utc)
    )

    # Postcondition.
    # A failed receipt names the RBAC fix, so the bundle README tells the
    # operator what to change.
    assert saved_receipts == [receipt]
    assert receipt.status is LogExportReceiptStatus.FAILED
    assert receipt.error is not None
    assert "logExport.kubernetesRbac.enabled" in receipt.error
