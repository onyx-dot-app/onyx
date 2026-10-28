"""Unit tests for the log export's Kubernetes API collector: which streams it
reads, how it caps them, and how it reports failures, against a fake API."""

import io
import json
import threading
import time
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


def _pod(
    name: str,
    component: str,
    restart_count: int = 0,
    init_container: str | None = None,
) -> client.V1Pod:
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
            init_container_statuses=[
                client.V1ContainerStatus(
                    name=init_container,
                    image="onyx",
                    image_id="onyx",
                    ready=False,
                    restart_count=0,
                    state=client.V1ContainerState(
                        terminated=client.V1ContainerStateTerminated(
                            exit_code=0, reason="Completed"
                        )
                    ),
                )
            ]
            if init_container
            else None,
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
    def __init__(self, data: bytes, chunk_delay_seconds: float) -> None:
        self._data = data
        self._chunk_delay_seconds = chunk_delay_seconds
        self.released = threading.Event()

    def stream(self, amt: int) -> Iterator[bytes]:
        for start in range(0, len(self._data), amt):
            time.sleep(self._chunk_delay_seconds)
            yield self._data[start : start + amt]

    def release_conn(self) -> None:
        self.released.set()


class _FakeCoreV1Api(client.CoreV1Api):
    """Serves fixed pods, logs, and events; ignores ``limit_bytes`` so the
    collector's own byte bound is exercised."""

    def __init__(
        self,
        pods: list[client.V1Pod],
        logs: dict[tuple[str, bool], bytes],
        events: list[client.CoreV1Event],
        read_pod_error: ApiException | None = None,
        chunk_delay_seconds: float = 0.0,
        open_errors: dict[tuple[str, bool], Exception] | None = None,
    ) -> None:
        self._pods = pods
        self._logs = logs
        self._events = events
        self._read_pod_error = read_pod_error
        self._chunk_delay_seconds = chunk_delay_seconds
        self._open_errors = open_errors or {}
        self.label_selectors: list[str] = []
        self.responses: list[_FakeLogResponse] = []

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
        if key in self._open_errors:
            raise self._open_errors[key]
        if key not in self._logs:
            raise ApiException(status=400, reason="Bad Request")
        response = _FakeLogResponse(self._logs[key], self._chunk_delay_seconds)
        self.responses.append(response)
        return response

    def list_namespaced_event(self, namespace: str, **_: Any) -> Any:
        assert namespace == _NAMESPACE
        return client.CoreV1EventList(items=self._events)


def _deadline(seconds: float) -> float:
    return time.monotonic() + seconds


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
    built = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(30.0))

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


def test_stream_byte_cap_truncates_a_log(monkeypatch: pytest.MonkeyPatch) -> None:
    # Precondition.
    # The log is larger than the per-log cap.
    monkeypatch.setattr(
        kubernetes_collection, "LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM", 10
    )
    api = _FakeCoreV1Api(
        pods=[_pod(_API_POD, "api-server")],
        logs={(_API_POD, False): b"a" * 100},
        events=[],
    )

    # Under test.
    built = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(30.0))

    # Postcondition.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert files[f"logs/{_API_POD}/api-server.log"] == b"a" * 10
    assert (
        "(10 bytes, truncated at the per-log byte cap)" in files["README.txt"].decode()
    )


def test_total_budget_runs_out_mid_stream_across_parallel_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Precondition.
    # Four logs of 100 bytes are read in parallel, 4 bytes per chunk, against a
    # 150-byte budget for the export.
    monkeypatch.setattr(kubernetes_collection, "_STREAM_READ_CHUNK_BYTES", 4)
    monkeypatch.setattr(
        kubernetes_collection, "LOG_EXPORT_KUBERNETES_MAX_TOTAL_BYTES", 150
    )
    pods = [_pod(f"onyx-worker-{i}-abc12-xyz{i}", f"worker-{i}") for i in range(4)]
    api = _FakeCoreV1Api(
        pods=pods,
        logs={(pod.metadata.name, False): b"x" * 100 for pod in pods},
        events=[],
        chunk_delay_seconds=0.001,
    )

    # Under test.
    built = build_kubernetes_log_zip(
        api, _NAMESPACE, pods[0].metadata.name, _deadline(30.0)
    )

    # Postcondition.
    # The logs together hold exactly the budget, and every log the budget cut
    # short is marked in the README.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    log_sizes = [len(data) for name, data in files.items() if name.startswith("logs/")]
    assert sum(log_sizes) == 150
    assert all(size <= 100 for size in log_sizes)
    readme = files["README.txt"].decode()
    capped_lines = [
        line for line in readme.splitlines() if "total byte cap reached" in line
    ]
    assert len(capped_lines) == 4 - log_sizes.count(100)


def test_deadline_stops_reads_and_releases_them() -> None:
    # Precondition.
    # The log arrives slowly, so reading all of it takes far longer than the
    # time budget.
    api = _FakeCoreV1Api(
        pods=[_pod(_API_POD, "api-server")],
        logs={(_API_POD, False): b"a" * (64 * 1024 * 100)},
        events=[],
        chunk_delay_seconds=0.05,
    )

    # Under test.
    built = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(0.2))

    # Postcondition.
    # The log is reported as timed out, and the read stops on its next chunk
    # instead of running on in the background.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert f"logs/{_API_POD}/api-server.log: timed out" in files["README.txt"].decode()
    [response] = api.responses
    assert response.released.wait(timeout=1.0)


def test_transport_error_on_one_log_keeps_the_others() -> None:
    # Precondition.
    # Opening one log fails below the Kubernetes client, e.g. a reset socket.
    pods = [
        _pod(_API_POD, "api-server"),
        _pod(_DOCPROCESSING_POD, "celery-worker-docprocessing"),
    ]
    api = _FakeCoreV1Api(
        pods=pods,
        logs={(_API_POD, False): b"api line\n", (_DOCPROCESSING_POD, False): b"x"},
        events=[],
        open_errors={(_DOCPROCESSING_POD, False): ConnectionResetError("reset")},
    )

    # Under test.
    built = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(30.0))

    # Postcondition.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert files[f"logs/{_API_POD}/api-server.log"] == b"api line\n"
    assert (
        f"logs/{_DOCPROCESSING_POD}/celery-worker-docprocessing.log: reset"
        in files["README.txt"].decode()
    )


def test_init_container_log_and_status_are_collected() -> None:
    # Precondition.
    # The pod ran an init container before its main container.
    pod = _pod(_API_POD, "api-server", init_container="wait-for-object-store")
    api = _FakeCoreV1Api(pods=[pod], logs={(_API_POD, False): b"line\n"}, events=[])

    # Under test.
    built = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(30.0))

    # Postcondition.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert f"logs/{_API_POD}/wait-for-object-store.log" in files
    [summary] = json.loads(files[PODS_FILE_NAME])
    assert [(c["name"], c["init"]) for c in summary["containers"]] == [
        ("wait-for-object-store", True),
        ("api-server", False),
    ]


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
