"""Kubernetes API collector for the admin log export.

File collection reaches one replica per worker type and only logs written to
disk. This collector runs in the api_server and reads, for every Onyx pod of the
Helm release, each container's stdout (plus the previous container after a
restart, e.g. an OOM kill), a pod status summary, and the namespace events for
those pods. It needs get/list on pods, pods/log, and events in its namespace,
which the Helm chart grants through ``logExport.kubernetesRbac``.
"""

import os
import socket
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from kubernetes import client
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel, TypeAdapter

from ee.onyx.configs.app_configs import (
    LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM,
    LOG_EXPORT_KUBERNETES_MAX_TOTAL_BYTES,
    LOG_EXPORT_KUBERNETES_TAIL_LINES,
)
from ee.onyx.server.log_export.collection import (
    README_FILE_NAME,
    SENSITIVE_DATA_WARNING,
    BuiltLogZip,
)
from ee.onyx.server.log_export.models import LogExportReceipt, LogExportReceiptStatus
from ee.onyx.server.log_export.storage import (
    KUBERNETES_PIECE_NAME,
    save_piece,
    save_receipt,
)
from onyx import __version__
from onyx.file_store.constants import MAX_IN_MEMORY_SIZE
from onyx.server.features.build.sandbox.kubernetes.k8s_client import (
    build_core_v1_api,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

KUBERNETES_WORKER_NAME = "kubernetes"

SERVICE_ACCOUNT_NAMESPACE_FILE = Path(
    "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
)

# Labels every pod of one Onyx Helm release carries (``onyx.selectorLabels``).
RELEASE_SELECTOR_LABELS = ("app.kubernetes.io/name", "app.kubernetes.io/instance")
# Per-component label set by the chart, e.g. ``celery-worker-docprocessing``.
COMPONENT_LABEL = "app"

PODS_FILE_NAME = "pods.json"
EVENTS_FILE_NAME = "events.txt"

_MAX_PARALLEL_STREAMS = 8
# Time kept after the log reads to zip and upload before the export deadline.
_UPLOAD_MARGIN_SECONDS = 15.0
_STREAM_READ_CHUNK_BYTES = 64 * 1024
_HTTP_FORBIDDEN = 403
_RBAC_HINT = (
    "The Kubernetes API denied access. Grant the api-server service account "
    "get/list on pods, pods/log, and events (Helm value "
    "logExport.kubernetesRbac.enabled)."
)
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


class LogStream(BaseModel):
    pod_name: str
    container_name: str
    # Reads the container instance that ran before the last restart.
    previous: bool

    @property
    def arcname(self) -> str:
        suffix = ".previous.log" if self.previous else ".log"
        return f"logs/{self.pod_name}/{self.container_name}{suffix}"


class TerminationSummary(BaseModel):
    reason: str | None
    exit_code: int | None
    started_at: datetime | None
    finished_at: datetime | None


class ContainerSummary(BaseModel):
    name: str
    ready: bool
    restart_count: int
    # ``running``, ``waiting: <reason>``, or ``terminated: <reason>``.
    state: str
    # How the previous instance ended, e.g. ``OOMKilled`` with exit code 137.
    last_terminated: TerminationSummary | None


class PodSummary(BaseModel):
    name: str
    component: str | None
    node: str | None
    phase: str | None
    # Pod-level reason and message, e.g. ``Evicted`` with the resource pressure.
    reason: str | None
    message: str | None
    containers: list[ContainerSummary]


class _FetchedStream:
    """One container log read into a spooled buffer, or the reason it failed."""

    def __init__(
        self,
        stream: LogStream,
        buffer: tempfile.SpooledTemporaryFile[bytes] | None,
        size_bytes: int,
        error: str | None,
    ) -> None:
        self.stream = stream
        self.buffer = buffer
        self.size_bytes = size_bytes
        self.error = error


def _container_state(container_status: client.V1ContainerStatus) -> str:
    state = container_status.state
    if state is None:
        return "unknown"
    if state.running is not None:
        return "running"
    if state.waiting is not None:
        return f"waiting: {state.waiting.reason}"
    if state.terminated is not None:
        return f"terminated: {state.terminated.reason}"
    return "unknown"


def summarize_pod(pod: client.V1Pod) -> PodSummary:
    containers: list[ContainerSummary] = []
    for container_status in pod.status.container_statuses or []:
        last_state = container_status.last_state
        terminated = last_state.terminated if last_state is not None else None
        containers.append(
            ContainerSummary(
                name=container_status.name,
                ready=bool(container_status.ready),
                restart_count=container_status.restart_count or 0,
                state=_container_state(container_status),
                last_terminated=TerminationSummary(
                    reason=terminated.reason,
                    exit_code=terminated.exit_code,
                    started_at=terminated.started_at,
                    finished_at=terminated.finished_at,
                )
                if terminated is not None
                else None,
            )
        )
    labels = pod.metadata.labels or {}
    return PodSummary(
        name=pod.metadata.name,
        component=labels.get(COMPONENT_LABEL),
        node=pod.spec.node_name,
        phase=pod.status.phase,
        reason=pod.status.reason,
        message=pod.status.message,
        containers=containers,
    )


def log_streams_for_pod(pod: client.V1Pod) -> list[LogStream]:
    """A started container has a current log; a restarted one also has the
    previous instance's log, which holds the crash."""
    streams: list[LogStream] = []
    for container_status in pod.status.container_statuses or []:
        state = container_status.state
        started = state is not None and (
            state.running is not None or state.terminated is not None
        )
        if started:
            streams.append(
                LogStream(
                    pod_name=pod.metadata.name,
                    container_name=container_status.name,
                    previous=False,
                )
            )
        if (container_status.restart_count or 0) > 0:
            streams.append(
                LogStream(
                    pod_name=pod.metadata.name,
                    container_name=container_status.name,
                    previous=True,
                )
            )
    return streams


def _fetch_stream(
    core_api: client.CoreV1Api, namespace: str, stream: LogStream
) -> _FetchedStream:
    try:
        response = core_api.read_namespaced_pod_log(
            name=stream.pod_name,
            namespace=namespace,
            container=stream.container_name,
            previous=stream.previous,
            tail_lines=LOG_EXPORT_KUBERNETES_TAIL_LINES,
            limit_bytes=LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM,
            _preload_content=False,
        )
    except ApiException as e:
        return _FetchedStream(stream, None, 0, f"{e.status} {e.reason}")

    buffer: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
        max_size=MAX_IN_MEMORY_SIZE
    )
    size_bytes = 0
    try:
        for chunk in response.stream(_STREAM_READ_CHUNK_BYTES):
            # The API honors limit_bytes; the bound here guards the export
            # against an API server that does not.
            chunk = chunk[: LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM - size_bytes]
            buffer.write(chunk)
            size_bytes += len(chunk)
            if size_bytes >= LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM:
                break
    except Exception as e:
        logger.warning(
            "Log export: reading %s failed: %s", stream.arcname, e, exc_info=True
        )
        buffer.close()
        return _FetchedStream(stream, None, 0, str(e))
    finally:
        response.release_conn()
    buffer.seek(0)
    return _FetchedStream(stream, buffer, size_bytes, None)


def _event_time(event: client.CoreV1Event) -> datetime:
    return (
        event.last_timestamp
        or event.event_time
        or event.first_timestamp
        or event.metadata.creation_timestamp
        or _EPOCH
    )


def _object_name_prefixes(pods: list[client.V1Pod]) -> set[str]:
    """Pod names plus their Deployment names, so events for pods that are
    already gone (evicted, replaced) and for the Deployments still match."""
    prefixes: set[str] = set()
    for pod in pods:
        prefixes.add(pod.metadata.name)
        for owner in pod.metadata.owner_references or []:
            if owner.kind == "ReplicaSet":
                prefixes.add(owner.name.rsplit("-", 1)[0])
    return prefixes


def format_events(events: list[client.CoreV1Event], pods: list[client.V1Pod]) -> str:
    prefixes = tuple(_object_name_prefixes(pods))
    lines: list[str] = []
    for event in sorted(events, key=_event_time):
        involved = event.involved_object
        if not involved.name or not involved.name.startswith(prefixes):
            continue
        lines.append(
            f"{_event_time(event).isoformat()} {event.type} {event.reason} "
            f"{involved.kind}/{involved.name} (x{event.count or 1}): "
            f"{(event.message or '').strip()}"
        )
    return "\n".join(lines) + "\n"


def _release_selector(core_api: client.CoreV1Api, namespace: str, pod_name: str) -> str:
    own_pod = core_api.read_namespaced_pod(name=pod_name, namespace=namespace)
    labels = own_pod.metadata.labels or {}
    parts: list[str] = []
    for label in RELEASE_SELECTOR_LABELS:
        value = labels.get(label)
        if value is None:
            raise ValueError(
                f"Pod {pod_name} has no {label} label, so the Onyx pods of its "
                "release cannot be selected."
            )
        parts.append(f"{label}={value}")
    return ",".join(parts)


def _build_readme(
    namespace: str,
    selector: str,
    written: list[_FetchedStream],
    failures: list[tuple[str, str]],
    events_error: str | None,
) -> str:
    lines = [
        "Onyx log export: Kubernetes API collection",
        "==========================================",
        "",
        SENSITIVE_DATA_WARNING,
        "",
        f"Namespace: {namespace}",
        f"Pod selector: {selector}",
        f"Collected by api_server pod: {socket.gethostname()}",
        f"Onyx version: {__version__}",
        f"Collected at (UTC): {datetime.now(tz=timezone.utc).isoformat()}",
        "",
        f"{PODS_FILE_NAME}: phase, restarts, and last termination (e.g. "
        "OOMKilled) of each container.",
        f"{EVENTS_FILE_NAME}: namespace events for these pods and their Deployments.",
        f"Each log holds at most the last {LOG_EXPORT_KUBERNETES_TAIL_LINES} "
        f"lines and {LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM} bytes.",
        "",
        "Included logs:",
    ]
    lines.extend(
        f"  {fetched.stream.arcname} ({fetched.size_bytes} bytes)"
        for fetched in written
    )
    if failures:
        lines.append("")
        lines.append("Logs not collected:")
        lines.extend(f"  {arcname}: {reason}" for arcname, reason in failures)
    if events_error:
        lines.append("")
        lines.append(f"Events not collected: {events_error}")
    lines.append("")
    return "\n".join(lines)


def build_kubernetes_log_zip(
    core_api: client.CoreV1Api,
    namespace: str,
    own_pod_name: str,
    time_budget_seconds: float,
) -> BuiltLogZip:
    """Reads the logs, status, and events of every Onyx pod of this release.

    A stream that fails, times out, or would pass the total byte cap is listed
    in the zip's README instead of failing the collection. Failing to select
    or list the pods raises.
    """
    selector = _release_selector(core_api, namespace, own_pod_name)
    pods = sorted(
        core_api.list_namespaced_pod(
            namespace=namespace, label_selector=selector
        ).items,
        key=lambda pod: pod.metadata.name,
    )

    streams = [stream for pod in pods for stream in log_streams_for_pod(pod)]
    fetched_streams: list[_FetchedStream] = run_functions_tuples_in_parallel(
        [(_fetch_stream, (core_api, namespace, stream)) for stream in streams],
        allow_failures=True,
        max_workers=_MAX_PARALLEL_STREAMS,
        timeout=time_budget_seconds,
        timeout_callback=lambda index, _func, _args: _FetchedStream(
            streams[index], None, 0, "timed out"
        ),
    )

    events_text = ""
    events_error: str | None = None
    try:
        events = core_api.list_namespaced_event(namespace=namespace).items
        events_text = format_events(events, pods)
    except ApiException as e:
        events_error = f"{e.status} {e.reason}"

    written: list[_FetchedStream] = []
    failures: list[tuple[str, str]] = []
    total_bytes = 0
    zip_buffer: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
        max_size=MAX_IN_MEMORY_SIZE
    )
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for fetched in fetched_streams:
            if fetched.buffer is None:
                failures.append((fetched.stream.arcname, fetched.error or "unknown"))
                continue
            with fetched.buffer:
                if (
                    total_bytes + fetched.size_bytes
                    > LOG_EXPORT_KUBERNETES_MAX_TOTAL_BYTES
                ):
                    failures.append((fetched.stream.arcname, "total byte cap reached"))
                    continue
                with zip_file.open(fetched.stream.arcname, mode="w") as destination:
                    while chunk := fetched.buffer.read(_STREAM_READ_CHUNK_BYTES):
                        destination.write(chunk)
                total_bytes += fetched.size_bytes
                written.append(fetched)

        zip_file.writestr(
            PODS_FILE_NAME,
            TypeAdapter(list[PodSummary]).dump_json(
                [summarize_pod(pod) for pod in pods], indent=2
            ),
        )
        zip_file.writestr(EVENTS_FILE_NAME, events_text)
        zip_file.writestr(
            README_FILE_NAME,
            _build_readme(namespace, selector, written, failures, events_error),
        )

    zip_buffer.seek(0, os.SEEK_END)
    size_bytes = zip_buffer.tell()
    zip_buffer.seek(0)
    return BuiltLogZip(
        zip_buffer=zip_buffer, log_file_count=len(written), size_bytes=size_bytes
    )


def collect_kubernetes_logs_into_file_store(
    export_id: str, deadline: datetime
) -> LogExportReceipt:
    """Uploads the Kubernetes API collection as a piece and writes its receipt.

    Runs off the request path. Any failure (including missing RBAC) becomes a
    ``FAILED`` receipt, so the export still completes with the other pieces.
    """
    hostname = socket.gethostname()
    status = LogExportReceiptStatus.FAILED
    file_count = 0
    size_bytes = 0
    error: str | None = None
    try:
        namespace = SERVICE_ACCOUNT_NAMESPACE_FILE.read_text().strip()
        time_budget_seconds = max(
            1.0,
            (deadline - datetime.now(tz=timezone.utc)).total_seconds()
            - _UPLOAD_MARGIN_SECONDS,
        )
        built = build_kubernetes_log_zip(
            core_api=build_core_v1_api(),
            namespace=namespace,
            own_pod_name=hostname,
            time_budget_seconds=time_budget_seconds,
        )
        try:
            save_piece(export_id, KUBERNETES_PIECE_NAME, built)
        finally:
            built.zip_buffer.close()
        status = LogExportReceiptStatus.UPLOADED
        file_count = built.log_file_count
        size_bytes = built.size_bytes
    except ApiException as e:
        logger.exception("Log export Kubernetes collection failed: %s", export_id)
        error = (
            _RBAC_HINT
            if e.status == _HTTP_FORBIDDEN
            else f"Kubernetes API error: {e.status} {e.reason}"
        )
    except Exception as e:
        logger.exception("Log export Kubernetes collection failed: %s", export_id)
        error = str(e)

    receipt = LogExportReceipt(
        export_id=export_id,
        worker_name=KUBERNETES_WORKER_NAME,
        hostname=hostname,
        status=status,
        file_count=file_count,
        size_bytes=size_bytes,
        collected_at=datetime.now(tz=timezone.utc),
        error=error,
    )
    save_receipt(receipt)
    return receipt
