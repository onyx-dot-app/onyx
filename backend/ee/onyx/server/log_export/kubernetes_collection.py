"""Kubernetes API collector for the admin log export.

File collection reaches one replica per worker type and only logs written to
disk. This collector runs in the api_server and reads, for every Onyx pod of the
Helm release, each container's stdout (plus the previous container after a
restart, e.g. an OOM kill), a pod status summary, and the namespace events for
those pods. It needs get/list on pods, pods/log, and events in its namespace,
which the Helm chart grants through ``logExport.kubernetesRbac.mode``.
"""

import os
import socket
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from kubernetes import client
from kubernetes.client.exceptions import ApiException
from pydantic import TypeAdapter

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
from ee.onyx.server.log_export.models import (
    ContainerSummary,
    KubernetesLogStream,
    LogExportReceipt,
    LogExportReceiptStatus,
    PodSummary,
    TerminationSummary,
)
from ee.onyx.server.log_export.storage import (
    KUBERNETES_PIECE_NAME,
    save_piece,
    save_receipt,
)
from onyx import __version__
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
# Set on ReplicaSet-owned pods; the ReplicaSet name is ``<deployment>-<hash>``.
POD_TEMPLATE_HASH_LABEL = "pod-template-hash"

PODS_FILE_NAME = "pods.json"
EVENTS_FILE_NAME = "events.txt"

_MAX_PARALLEL_STREAMS = 8
# Time kept after the log reads to zip and upload before the export deadline.
# It must exceed _MAX_READ_SECONDS, the longest one blocked read can run late.
_UPLOAD_MARGIN_SECONDS = 15.0
_CONNECT_SECONDS = 5.0
_MAX_READ_SECONDS = 10.0
_STREAM_READ_CHUNK_BYTES = 64 * 1024
# Logs spool to disk past this size, so parallel reads hold little memory.
_SPOOL_MAX_MEMORY_BYTES = 1024 * 1024
_TIMED_OUT = "timed out"
_STREAM_CAP_REACHED = "truncated at the per-log byte cap"
_TOTAL_CAP_REACHED = "total byte cap reached"
_HTTP_FORBIDDEN = 403
_RBAC_HINT = (
    "The Kubernetes API denied access to pods, pods/log, or events. The Helm "
    "chart grants it only to a named service account by default "
    "(logExport.kubernetesRbac.mode=auto). To fix: set serviceAccount.create=true "
    "(move any IRSA or Workload Identity annotation to serviceAccount.annotations "
    "and update the IAM trust policy), or set logExport.kubernetesRbac.mode=true "
    "to also grant it to the namespace's default service account."
)
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)
# Workload kinds whose pods are named ``<owner name>-<suffix>``.
_POD_OWNER_KINDS = frozenset({"ReplicaSet", "StatefulSet", "DaemonSet", "Job"})


class _FetchedStream:
    """One container log, possibly partial, or the reason none of it was kept.

    Every byte charged to the byte budget stays in ``buffer``, so the budget
    never counts bytes the zip leaves out.
    """

    def __init__(
        self,
        stream: KubernetesLogStream,
        buffer: tempfile.SpooledTemporaryFile[bytes] | None,
        size_bytes: int,
        error: str | None,
        denied: bool = False,
        note: str | None = None,
    ) -> None:
        self.stream = stream
        self.buffer = buffer
        self.size_bytes = size_bytes
        # Why nothing was kept; set only when ``buffer`` is None.
        self.error = error
        # The API refused the read with 403.
        self.denied = denied
        # Why a kept log is incomplete, e.g. a byte cap or the deadline.
        self.note = note


class _ByteBudget:
    """Total bytes all parallel reads of one export may keep, reserved per
    chunk before it is written."""

    def __init__(self, total_bytes: int) -> None:
        self._remaining = total_bytes
        self._lock = threading.Lock()

    def reserve(self, requested_bytes: int) -> int:
        """Returns how many of the requested bytes may be kept (0 when spent)."""
        with self._lock:
            granted = min(requested_bytes, self._remaining)
            self._remaining -= granted
            return granted


def _request_timeout(deadline_monotonic: float) -> tuple[float, float]:
    """(connect, read) timeout for one request. The client ignores a lone float,
    so this is always a pair. At least 1 s, so a late request still gets a
    chance."""
    remaining = max(1.0, deadline_monotonic - time.monotonic())
    return min(_CONNECT_SECONDS, remaining), min(_MAX_READ_SECONDS, remaining)


def _container_statuses(
    pod: client.V1Pod,
) -> list[tuple[bool, client.V1ContainerStatus]]:
    """Init container statuses first, each paired with whether it is one."""
    return [(True, status) for status in pod.status.init_container_statuses or []] + [
        (False, status) for status in pod.status.container_statuses or []
    ]


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
    for init, container_status in _container_statuses(pod):
        last_state = container_status.last_state
        terminated = last_state.terminated if last_state is not None else None
        containers.append(
            ContainerSummary(
                name=container_status.name,
                init=init,
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


def log_streams_for_pod(pod: client.V1Pod) -> list[KubernetesLogStream]:
    """A started container has a current log; a restarted one also has the
    previous instance's log, which holds the crash."""
    streams: list[KubernetesLogStream] = []
    for _init, container_status in _container_statuses(pod):
        state = container_status.state
        started = state is not None and (
            state.running is not None or state.terminated is not None
        )
        if started:
            streams.append(
                KubernetesLogStream(
                    pod_name=pod.metadata.name,
                    container_name=container_status.name,
                    previous=False,
                )
            )
        if (container_status.restart_count or 0) > 0:
            streams.append(
                KubernetesLogStream(
                    pod_name=pod.metadata.name,
                    container_name=container_status.name,
                    previous=True,
                )
            )
    return streams


def _fetch_stream(
    core_api: client.CoreV1Api,
    namespace: str,
    stream: KubernetesLogStream,
    budget: _ByteBudget,
    deadline_monotonic: float,
) -> _FetchedStream:
    """Reads one log until it ends, hits a byte cap, fails, or passes the
    deadline. Never raises: whatever was read is kept and marked, so one bad
    log cannot drop the others."""
    if time.monotonic() >= deadline_monotonic:
        return _FetchedStream(stream, None, 0, _TIMED_OUT)
    try:
        response = core_api.read_namespaced_pod_log(
            name=stream.pod_name,
            namespace=namespace,
            container=stream.container_name,
            previous=stream.previous,
            tail_lines=LOG_EXPORT_KUBERNETES_TAIL_LINES,
            limit_bytes=LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM,
            _preload_content=False,
            _request_timeout=_request_timeout(deadline_monotonic),
        )
    except ApiException as e:
        return _FetchedStream(
            stream,
            None,
            0,
            f"{e.status} {e.reason}",
            denied=e.status == _HTTP_FORBIDDEN,
        )
    except Exception as e:
        logger.warning(
            "Log export: opening %s failed: %s", stream.arcname, e, exc_info=True
        )
        return _FetchedStream(stream, None, 0, str(e))

    buffer: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
        max_size=_SPOOL_MAX_MEMORY_BYTES
    )
    size_bytes = 0
    note: str | None = None
    try:
        for chunk in response.stream(_STREAM_READ_CHUNK_BYTES):
            if time.monotonic() >= deadline_monotonic:
                note = _TIMED_OUT
                break
            # The API honors limit_bytes; this bound guards against one that
            # does not.
            wanted = min(
                len(chunk), LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM - size_bytes
            )
            granted = budget.reserve(wanted)
            buffer.write(chunk[:granted])
            size_bytes += granted
            if granted < wanted:
                note = _TOTAL_CAP_REACHED
                break
            if size_bytes >= LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM:
                note = _STREAM_CAP_REACHED
                break
    except Exception as e:
        logger.warning(
            "Log export: reading %s failed: %s", stream.arcname, e, exc_info=True
        )
        note = f"read failed: {e}"
    finally:
        response.release_conn()

    if size_bytes == 0 and note is not None:
        buffer.close()
        return _FetchedStream(stream, None, 0, note)
    buffer.seek(0)
    return _FetchedStream(stream, buffer, size_bytes, None, note=note)


def _event_time(event: client.CoreV1Event) -> datetime:
    return (
        event.last_timestamp
        or event.event_time
        or event.first_timestamp
        or event.metadata.creation_timestamp
        or _EPOCH
    )


class _EventScope:
    """The objects whose events belong to the collected pods: each pod, its
    owner, the Deployment behind a ReplicaSet, and owner-named pods that are
    already gone (evicted or replaced). Names match exactly, never by prefix."""

    def __init__(self, pods: list[client.V1Pod]) -> None:
        self._objects: set[tuple[str, str]] = set()
        self._pod_owner_names: set[str] = set()
        for pod in pods:
            self._objects.add(("Pod", pod.metadata.name))
            pod_template_hash = (pod.metadata.labels or {}).get(POD_TEMPLATE_HASH_LABEL)
            for owner in pod.metadata.owner_references or []:
                self._objects.add((owner.kind, owner.name))
                if owner.kind in _POD_OWNER_KINDS:
                    self._pod_owner_names.add(owner.name)
                if owner.kind == "ReplicaSet" and pod_template_hash:
                    deployment = owner.name.removesuffix(f"-{pod_template_hash}")
                    self._objects.add(("Deployment", deployment))
                    self._objects.add(("HorizontalPodAutoscaler", deployment))

    def includes(self, kind: str, name: str) -> bool:
        if (kind, name) in self._objects:
            return True
        return kind == "Pod" and name.rsplit("-", 1)[0] in self._pod_owner_names


def format_events(events: list[client.CoreV1Event], pods: list[client.V1Pod]) -> str:
    scope = _EventScope(pods)
    lines: list[str] = []
    for event in sorted(events, key=_event_time):
        involved = event.involved_object
        if not involved.kind or not involved.name:
            continue
        if not scope.includes(involved.kind, involved.name):
            continue
        lines.append(
            f"{_event_time(event).isoformat()} {event.type} {event.reason} "
            f"{involved.kind}/{involved.name} (x{event.count or 1}): "
            f"{(event.message or '').strip()}"
        )
    return "\n".join(lines) + "\n"


def _release_selector(
    core_api: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    deadline_monotonic: float,
) -> str:
    own_pod = core_api.read_namespaced_pod(
        name=pod_name,
        namespace=namespace,
        _request_timeout=_request_timeout(deadline_monotonic),
    )
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
        f"{EVENTS_FILE_NAME}: namespace events for these pods, their owners, and "
        "their Deployments.",
        f"Each log holds at most the last {LOG_EXPORT_KUBERNETES_TAIL_LINES} "
        f"lines and {LOG_EXPORT_KUBERNETES_MAX_BYTES_PER_STREAM} bytes.",
        "",
        "Included logs:",
    ]
    lines.extend(
        f"  {fetched.stream.arcname} ({fetched.size_bytes} bytes"
        + (f", incomplete: {fetched.note})" if fetched.note else ")")
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
    deadline_monotonic: float,
) -> tuple[BuiltLogZip, list[str]]:
    """Reads the logs, status, and events of every Onyx pod of this release.

    The reads share one total byte budget and stop at the deadline. A log that
    fails, times out, or is cut short is listed in the zip's README instead of
    failing the collection. Failing to select or list the pods raises.

    Returns:
        The zip, and the resources the API denied (e.g. ``pods/log``), so the
        caller can report partial access.
    """
    selector = _release_selector(core_api, namespace, own_pod_name, deadline_monotonic)
    pods = sorted(
        core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=selector,
            _request_timeout=_request_timeout(deadline_monotonic),
        ).items,
        key=lambda pod: pod.metadata.name,
    )

    streams = [stream for pod in pods for stream in log_streams_for_pod(pod)]
    budget = _ByteBudget(LOG_EXPORT_KUBERNETES_MAX_TOTAL_BYTES)
    # No pool timeout: each read stops itself at the deadline, so every result
    # (and its charged bytes) comes back and no buffer is left behind.
    fetched_streams: list[_FetchedStream] = run_functions_tuples_in_parallel(
        [
            (_fetch_stream, (core_api, namespace, stream, budget, deadline_monotonic))
            for stream in streams
        ],
        allow_failures=False,
        max_workers=_MAX_PARALLEL_STREAMS,
    )

    denied: list[str] = []
    denied_logs = sum(fetched.denied for fetched in fetched_streams)
    if denied_logs:
        denied.append(f"pods/log ({denied_logs} of {len(streams)} logs)")

    events_text = ""
    events_error: str | None = None
    if time.monotonic() >= deadline_monotonic:
        events_error = "skipped: the time budget was spent on the logs"
    else:
        try:
            events = core_api.list_namespaced_event(
                namespace=namespace,
                _request_timeout=_request_timeout(deadline_monotonic),
            ).items
            events_text = format_events(events, pods)
        except ApiException as e:
            events_error = f"{e.status} {e.reason}"
            if e.status == _HTTP_FORBIDDEN:
                denied.append("events")
        except Exception as e:
            logger.warning("Log export: listing events failed: %s", e, exc_info=True)
            events_error = str(e)

    written: list[_FetchedStream] = []
    failures: list[tuple[str, str]] = []
    zip_buffer: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
        max_size=_SPOOL_MAX_MEMORY_BYTES
    )
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for fetched in fetched_streams:
            if fetched.buffer is None:
                failures.append((fetched.stream.arcname, fetched.error or "unknown"))
                continue
            with (
                fetched.buffer,
                zip_file.open(fetched.stream.arcname, mode="w") as destination,
            ):
                while chunk := fetched.buffer.read(_STREAM_READ_CHUNK_BYTES):
                    destination.write(chunk)
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
    built = BuiltLogZip(
        zip_buffer=zip_buffer, log_file_count=len(written), size_bytes=size_bytes
    )
    return built, denied


def collect_kubernetes_logs_into_file_store(
    export_id: str, deadline: datetime
) -> LogExportReceipt:
    """Uploads the Kubernetes API collection as a piece and writes its receipt.

    Runs off the request path. Any failure (including missing RBAC) becomes a
    ``FAILED`` receipt, so the export still completes with the other pieces. A
    piece the API partly denied is ``UPLOADED`` with the RBAC fix as its error.
    """
    hostname = socket.gethostname()
    status = LogExportReceiptStatus.FAILED
    file_count = 0
    size_bytes = 0
    error: str | None = None
    try:
        # One absolute deadline for every request, so pod discovery and events
        # cannot push the piece past the export deadline.
        deadline_monotonic = time.monotonic() + max(
            1.0,
            (deadline - datetime.now(tz=timezone.utc)).total_seconds()
            - _UPLOAD_MARGIN_SECONDS,
        )
        namespace = SERVICE_ACCOUNT_NAMESPACE_FILE.read_text().strip()
        built, denied = build_kubernetes_log_zip(
            core_api=build_core_v1_api(),
            namespace=namespace,
            own_pod_name=hostname,
            deadline_monotonic=deadline_monotonic,
        )
        try:
            save_piece(export_id, KUBERNETES_PIECE_NAME, built)
        finally:
            built.zip_buffer.close()
        status = LogExportReceiptStatus.UPLOADED
        file_count = built.log_file_count
        size_bytes = built.size_bytes
        if denied:
            error = f"{_RBAC_HINT} Denied: {', '.join(denied)}."
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
