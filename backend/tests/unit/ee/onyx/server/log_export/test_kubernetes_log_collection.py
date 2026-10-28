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
    """A ReplicaSet-owned pod named ``<deployment>-<hash>-<suffix>``."""
    replica_set, _suffix = name.rsplit("-", 1)
    pod_template_hash = replica_set.rsplit("-", 1)[1]
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
            labels={
                **_RELEASE_LABELS,
                "app": component,
                "pod-template-hash": pod_template_hash,
            },
            owner_references=[
                client.V1OwnerReference(
                    api_version="apps/v1", kind="ReplicaSet", name=replica_set, uid="u"
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


def _event(
    object_name: str, reason: str, message: str, kind: str = "Pod"
) -> client.CoreV1Event:
    return client.CoreV1Event(
        metadata=client.V1ObjectMeta(name=f"{object_name}.1"),
        involved_object=client.V1ObjectReference(kind=kind, name=object_name),
        reason=reason,
        message=message,
        type="Warning",
        count=1,
        last_timestamp=_T0,
    )


class _FakeLogResponse:
    def __init__(
        self,
        data: bytes,
        chunk_delay_seconds: float,
        error_after_first_chunk: Exception | None,
    ) -> None:
        self._data = data
        self._chunk_delay_seconds = chunk_delay_seconds
        self._error_after_first_chunk = error_after_first_chunk
        self.released = threading.Event()

    def stream(self, amt: int) -> Iterator[bytes]:
        for start in range(0, len(self._data), amt):
            time.sleep(self._chunk_delay_seconds)
            yield self._data[start : start + amt]
            if self._error_after_first_chunk is not None:
                raise self._error_after_first_chunk

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
        read_errors: dict[tuple[str, bool], Exception] | None = None,
        events_error: ApiException | None = None,
    ) -> None:
        self._pods = pods
        self._logs = logs
        self._events = events
        self._read_pod_error = read_pod_error
        self._chunk_delay_seconds = chunk_delay_seconds
        self._open_errors = open_errors or {}
        self._read_errors = read_errors or {}
        self._events_error = events_error
        self.label_selectors: list[str] = []
        self.request_timeouts: list[Any] = []
        self.responses: list[_FakeLogResponse] = []

    def read_namespaced_pod(self, name: str, namespace: str, **kwargs: Any) -> Any:
        assert namespace == _NAMESPACE
        self.request_timeouts.append(kwargs["_request_timeout"])
        if self._read_pod_error is not None:
            raise self._read_pod_error
        return next(pod for pod in self._pods if pod.metadata.name == name)

    def list_namespaced_pod(self, namespace: str, **kwargs: Any) -> Any:
        assert namespace == _NAMESPACE
        self.request_timeouts.append(kwargs["_request_timeout"])
        self.label_selectors.append(kwargs["label_selector"])
        return client.V1PodList(items=self._pods)

    def read_namespaced_pod_log(self, name: str, namespace: str, **kwargs: Any) -> Any:
        assert namespace == _NAMESPACE
        self.request_timeouts.append(kwargs["_request_timeout"])
        key = (name, bool(kwargs["previous"]))
        if key in self._open_errors:
            raise self._open_errors[key]
        if key not in self._logs:
            raise ApiException(status=400, reason="Bad Request")
        response = _FakeLogResponse(
            self._logs[key], self._chunk_delay_seconds, self._read_errors.get(key)
        )
        self.responses.append(response)
        return response

    def list_namespaced_event(self, namespace: str, **kwargs: Any) -> Any:
        assert namespace == _NAMESPACE
        self.request_timeouts.append(kwargs["_request_timeout"])
        if self._events_error is not None:
            raise self._events_error
        return client.CoreV1EventList(items=self._events)


def _deadline(seconds: float) -> float:
    return time.monotonic() + seconds


def _read_zip(built_buffer: Any) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(built_buffer.read())) as zip_file:
        return {name: zip_file.read(name) for name in zip_file.namelist()}


def _patch_collection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, api: _FakeCoreV1Api
) -> list[LogExportReceipt]:
    namespace_file = tmp_path / "namespace"
    namespace_file.write_text(_NAMESPACE)
    monkeypatch.setattr(
        kubernetes_collection, "SERVICE_ACCOUNT_NAMESPACE_FILE", namespace_file
    )
    monkeypatch.setattr(kubernetes_collection, "build_core_v1_api", lambda: api)
    monkeypatch.setattr(kubernetes_collection.socket, "gethostname", lambda: _API_POD)
    monkeypatch.setattr(kubernetes_collection, "save_piece", lambda *_: None)
    saved_receipts: list[LogExportReceipt] = []
    monkeypatch.setattr(kubernetes_collection, "save_receipt", saved_receipts.append)
    return saved_receipts


def test_restarted_container_collects_previous_log_and_termination() -> None:
    # Precondition.
    # The docprocessing container was OOM-killed once; its previous instance
    # holds the crash.
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
        events=[],
    )

    # Under test.
    built, denied = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(30.0))

    # Postcondition.
    # Both instances of the restarted container are collected, the pods are
    # selected by the release labels, and every request has a (connect, read)
    # timeout, the only form the client applies besides an int.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert denied == []
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
    assert all(
        isinstance(timeout, tuple) and len(timeout) == 2
        for timeout in api.request_timeouts
    )
    pod_summaries = json.loads(files[PODS_FILE_NAME])
    docprocessing = next(
        pod for pod in pod_summaries if pod["name"] == _DOCPROCESSING_POD
    )
    assert docprocessing["component"] == "celery-worker-docprocessing"
    assert docprocessing["containers"][0]["restart_count"] == 1
    assert docprocessing["containers"][0]["last_terminated"]["reason"] == "OOMKilled"


def test_events_match_exact_objects_of_collected_pods() -> None:
    # Precondition.
    # Events exist for a collected pod, a replaced pod of the same ReplicaSet,
    # the Deployment, and two look-alikes: a canary Deployment and its pod.
    api = _FakeCoreV1Api(
        pods=[_pod(_DOCPROCESSING_POD, "celery-worker-docprocessing")],
        logs={(_DOCPROCESSING_POD, False): b"line\n"},
        events=[
            _event(_DOCPROCESSING_POD, "BackOff", "restarting failed container"),
            _event("onyx-celery-worker-docprocessing-95f84-old11", "Evicted", "memory"),
            _event(
                "onyx-celery-worker-docprocessing",
                "ScalingReplicaSet",
                "scaled",
                kind="Deployment",
            ),
            _event(
                "onyx-celery-worker-docprocessing-canary",
                "CanaryScaled",
                "canary",
                kind="Deployment",
            ),
            _event(
                "onyx-celery-worker-docprocessing-canary-5c6d7-zz9yy",
                "CanaryPod",
                "canary pod",
            ),
        ],
    )

    # Under test.
    built, _ = build_kubernetes_log_zip(
        api, _NAMESPACE, _DOCPROCESSING_POD, _deadline(30.0)
    )

    # Postcondition.
    events = _read_zip(built.zip_buffer)[EVENTS_FILE_NAME].decode()
    built.zip_buffer.close()
    assert "BackOff" in events
    assert "Evicted" in events
    assert "ScalingReplicaSet" in events
    assert "Canary" not in events


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
    built, _ = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(30.0))

    # Postcondition.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert files[f"logs/{_API_POD}/api-server.log"] == b"a" * 10
    assert (
        "(10 bytes, incomplete: truncated at the per-log byte cap)"
        in files["README.txt"].decode()
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
    built, _ = build_kubernetes_log_zip(
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


def test_deadline_stops_reads_and_keeps_what_was_read() -> None:
    # Precondition.
    # The log arrives slowly, so reading all of it takes far longer than the
    # time budget.
    api = _FakeCoreV1Api(
        pods=[_pod(_API_POD, "api-server")],
        logs={(_API_POD, False): b"a" * (64 * 1024 * 100)},
        events=[],
        chunk_delay_seconds=0.05,
    )
    started = time.monotonic()

    # Under test.
    built, _ = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(0.2))

    # Postcondition.
    # The read stops on its next chunk and releases its connection; the bytes
    # it read stay in the zip, marked as timed out.
    elapsed = time.monotonic() - started
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert elapsed < 2.0
    [response] = api.responses
    assert response.released.is_set()
    readme = files["README.txt"].decode()
    [log_line] = [line for line in readme.splitlines() if "api-server.log" in line]
    assert "incomplete: timed out" in log_line
    kept = files[f"logs/{_API_POD}/api-server.log"]
    assert 0 < len(kept) < 64 * 1024 * 100


def test_read_failure_keeps_partial_log() -> None:
    # Precondition.
    # The connection drops after the first chunk of one log.
    api = _FakeCoreV1Api(
        pods=[_pod(_API_POD, "api-server")],
        logs={(_API_POD, False): b"a" * (64 * 1024 * 3)},
        events=[],
        read_errors={(_API_POD, False): ConnectionResetError("reset")},
    )

    # Under test.
    built, _ = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(30.0))

    # Postcondition.
    # The bytes read (and charged to the budget) stay in the zip, marked.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert files[f"logs/{_API_POD}/api-server.log"] == b"a" * (64 * 1024)
    assert "incomplete: read failed: reset" in files["README.txt"].decode()


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
    built, _ = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(30.0))

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
    built, _ = build_kubernetes_log_zip(api, _NAMESPACE, _API_POD, _deadline(30.0))

    # Postcondition.
    files = _read_zip(built.zip_buffer)
    built.zip_buffer.close()
    assert f"logs/{_API_POD}/wait-for-object-store.log" in files
    [summary] = json.loads(files[PODS_FILE_NAME])
    assert [(c["name"], c["init"]) for c in summary["containers"]] == [
        ("wait-for-object-store", True),
        ("api-server", False),
    ]


def test_denied_logs_and_events_mark_the_uploaded_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Precondition.
    # The service account may list pods but may not read pods/log or events.
    api = _FakeCoreV1Api(
        pods=[_pod(_API_POD, "api-server")],
        logs={},
        events=[],
        open_errors={(_API_POD, False): ApiException(status=403, reason="Forbidden")},
        events_error=ApiException(status=403, reason="Forbidden"),
    )
    saved_receipts = _patch_collection(monkeypatch, tmp_path, api)

    # Under test.
    receipt = collect_kubernetes_logs_into_file_store(
        export_id="export", deadline=datetime.now(tz=timezone.utc)
    )

    # Postcondition.
    # The partial piece (pod status) is kept, and the receipt names the
    # denied resources and the RBAC fix.
    assert saved_receipts == [receipt]
    assert receipt.status is LogExportReceiptStatus.UPLOADED
    assert receipt.error is not None
    assert "logExport.kubernetes.enabled=true" in receipt.error
    assert "pods/log (1 of 1 logs)" in receipt.error
    assert "events" in receipt.error


def test_missing_rbac_writes_failed_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Precondition.
    # The service account may not read pods.
    api = _FakeCoreV1Api(
        pods=[],
        logs={},
        events=[],
        read_pod_error=ApiException(status=403, reason="Forbidden"),
    )
    saved_receipts = _patch_collection(monkeypatch, tmp_path, api)

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
    assert "logExport.kubernetes.enabled=true" in receipt.error
