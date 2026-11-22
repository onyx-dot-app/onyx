"""In-process fake of the Firecracker host agent gRPC server, with a fake guest
daemon behind its pass-through."""

import hashlib
import io
import itertools
import os
import posixpath
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import zlib
from collections.abc import Iterator
from concurrent import futures
from dataclasses import dataclass, field
from typing import Any

import grpc
from google.rpc import error_details_pb2, status_pb2

from onyx.microvm.agent_client import (
    HOST_AGENT_ERROR_DOMAIN,
    MAX_MESSAGE_BYTES,
    HostAgentClient,
    HostAgentClientFactory,
    HostAgentErrorReason,
)
from onyx.microvm.daemon_client import (
    SANDBOX_ID_HEADER,
    SANDBOXD_ERROR_DOMAIN,
    SANDBOXD_KEY_HEADER,
    SandboxDaemonErrorReason,
)
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2, hostagent_pb2_grpc
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2, sandboxd_pb2_grpc

_REASON_CODES: dict[HostAgentErrorReason, grpc.StatusCode] = {
    HostAgentErrorReason.CAPACITY_MEMORY: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.CAPACITY_DISK: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.CAPACITY_VM_SLOTS: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.ATTEMPT_CONFLICT: grpc.StatusCode.ALREADY_EXISTS,
    HostAgentErrorReason.STALE_ATTEMPT: grpc.StatusCode.FAILED_PRECONDITION,
    HostAgentErrorReason.SANDBOX_NOT_FOUND: grpc.StatusCode.NOT_FOUND,
    HostAgentErrorReason.INSTANCE_MISMATCH: grpc.StatusCode.FAILED_PRECONDITION,
    HostAgentErrorReason.GUEST_UNREACHABLE: grpc.StatusCode.UNAVAILABLE,
    HostAgentErrorReason.METHOD_NOT_ALLOWED: grpc.StatusCode.PERMISSION_DENIED,
    HostAgentErrorReason.DIAL_LIMIT: grpc.StatusCode.RESOURCE_EXHAUSTED,
    HostAgentErrorReason.CAPTURE_NOT_FOUND: grpc.StatusCode.NOT_FOUND,
    HostAgentErrorReason.MANAGED_IMAGE_MISSING: grpc.StatusCode.NOT_FOUND,
    HostAgentErrorReason.MANAGED_BUNDLE_INVALID: grpc.StatusCode.INVALID_ARGUMENT,
    HostAgentErrorReason.TRANSFER_FAILED: grpc.StatusCode.UNAVAILABLE,
    HostAgentErrorReason.VM_NOT_RUNNING: grpc.StatusCode.FAILED_PRECONDITION,
    HostAgentErrorReason.EGRESS_CA_UNAVAILABLE: grpc.StatusCode.UNAVAILABLE,
}

# As microvm/internal/guestd/errors.go.
_DAEMON_REASON_CODES: dict[SandboxDaemonErrorReason, grpc.StatusCode] = {
    SandboxDaemonErrorReason.INVALID_ARGUMENT: grpc.StatusCode.INVALID_ARGUMENT,
    SandboxDaemonErrorReason.START_FAILED: grpc.StatusCode.INVALID_ARGUMENT,
    SandboxDaemonErrorReason.UNAUTHENTICATED: grpc.StatusCode.UNAUTHENTICATED,
    SandboxDaemonErrorReason.EXECUTION_NOT_FOUND: grpc.StatusCode.NOT_FOUND,
    SandboxDaemonErrorReason.FILE_NOT_FOUND: grpc.StatusCode.NOT_FOUND,
    SandboxDaemonErrorReason.FILE_EXISTS: grpc.StatusCode.ALREADY_EXISTS,
    SandboxDaemonErrorReason.LIMIT_EXCEEDED: grpc.StatusCode.RESOURCE_EXHAUSTED,
    SandboxDaemonErrorReason.EXECUTION_CAP_REACHED: grpc.StatusCode.RESOURCE_EXHAUSTED,
}

# The guest daemon's files.TopFilesRoot.
TOP_FILES_ROOT = ".onyx-top-level"
WORKSPACES = "/home/onyx/workspaces"
# Absolute paths that the daemon refuses with no session ID.
_DENIED_VM_PATHS = ("/proc", "/sys", "/dev", "/run/craft-fc")
# The daemon streams output in chunks of at most this size (guestd server.go).
_STREAM_CHUNK_BYTES = 64 << 10
# What the fake pdftoppm writes; tests compare the bytes.
FAKE_JPEG = b"\xff\xd8\xff\xe0fake-first-page\xff\xd9"


def _abort(
    context: grpc.ServicerContext,
    code: grpc.StatusCode,
    domain: str,
    reason: str,
    message: str,
) -> None:
    status = status_pb2.Status(code=code.value[0], message=message)
    status.details.add().Pack(error_details_pb2.ErrorInfo(reason=reason, domain=domain))
    context.set_trailing_metadata(
        (("grpc-status-details-bin", status.SerializeToString()),)
    )
    context.abort(code, message)


def abort_with_reason(
    context: grpc.ServicerContext, reason: HostAgentErrorReason, message: str
) -> None:
    code = _REASON_CODES.get(reason, grpc.StatusCode.FAILED_PRECONDITION)
    _abort(context, code, HOST_AGENT_ERROR_DOMAIN, reason.value, message)


def abort_daemon(
    context: grpc.ServicerContext, reason: SandboxDaemonErrorReason, message: str
) -> None:
    code = _DAEMON_REASON_CODES.get(reason, grpc.StatusCode.FAILED_PRECONDITION)
    _abort(context, code, SANDBOXD_ERROR_DOMAIN, reason.value, message)


class FakeHostAgent(hostagent_pb2_grpc.HostAgentServicer):
    """One node. VMs live in memory; tests change the knobs between calls."""

    def __init__(
        self,
        *,
        mem_available_mib: int = 16_384,
        template: str = "tpl-1",
        template_mem_mib: int = 2048,
    ) -> None:
        self.lock = threading.Lock()
        # Notified when an execution ends.
        self.ended = threading.Condition(self.lock)
        self.mem_available_mib = mem_available_mib
        self.templates = [
            hostagent_pb2.TemplateInfo(
                version=template,
                vcpus=2,
                mem_mib=template_mem_mib,
                scratch_gib=4,
                guest_kernel="6.18.25",
                firecracker_version="v1.17.0",
                managed_mounts=["skills", "user-uploads", "spaces"],
            )
        ]
        self.vms: dict[str, hostagent_pb2.VM] = {}
        self.refuse_create: HostAgentErrorReason | None = None
        self.max_vms = 0
        # Slots of template builds and processes in doubt.
        self.other_slots = 0
        # With refuse_create: refuse only this many more Creates (None: all).
        self.refuse_create_times: int | None = None
        self.next_generation = 1_000
        self.create_calls = 0
        self.list_calls = 0
        self.stop_calls: list[tuple[str, int, int]] = []
        # (sandbox_id, attempt, sandboxd_key) of every Create.
        self.create_requests: list[tuple[str, int, str]] = []
        # The key each guest daemon holds (its SetKey state).
        self.daemon_keys: dict[str, str] = {}
        # The next N key installs time out (GUEST_UNREACHABLE).
        self.guest_unreachable_creates = 0
        # The next N Creates start the VM, then fail with no reason (a lost
        # answer, e.g. a deadline): the caller cannot know the VM runs.
        self.lost_create_answers = 0
        self.init_requests: list[tuple[sandboxd_pb2.InitRequest, str]] = []
        # The generation of each guest daemon's last Init (its Health).
        self.daemon_inits: dict[str, int] = {}
        # Guest daemon executions and session files, by sandbox.
        self.executions: dict[str, dict[str, FakeExecution]] = {}
        # (sandbox_id, session_id, path) -> bytes of a regular file. A call
        # with no session ID keeps its absolute path, with session_id "".
        self.files: dict[tuple[str, str, str], bytes] = {}
        # Permission bits of a file in `files`; 0o644 when absent.
        self.file_modes: dict[tuple[str, str, str], int] = {}
        # Each file's modification time in seconds since the epoch, set by a
        # write; a file with none lists no modified_at.
        self.file_times: dict[tuple[str, str, str], float] = {}
        # (sandbox_id, session_id, path) -> target of a symlink, as stored.
        self.links: dict[tuple[str, str, str], str] = {}
        # The next RenameFile happens, then its reply is lost.
        self.lose_rename_reply = False
        # StatFiles facts of a path, as the guest daemon's os.Root reports
        # them (the Go tests own those rules). Other paths get the facts of
        # their own entry, and a link names nothing.
        self.path_stats: dict[tuple[str, str, str], sandboxd_pb2.PathStat] = {}
        # The data message sizes of each WriteFile, in order.
        self.write_chunk_sizes: list[list[int]] = []
        # Injected WriteFile failures, by path as the daemon takes it
        # (session-relative, or absolute with no session), or ANY_PATH.
        self.write_failures: dict[str, WriteFailure] = {}
        # The path of each WriteFile, as the daemon takes it, in order.
        self.write_paths: list[str] = []
        # By path: WriteFile waits for the event after all data arrived,
        # before it stores; the path is in write_waiting meanwhile.
        self.write_gates: dict[str, threading.Event] = {}
        self.write_waiting: set[str] = set()
        # By path: WriteFile waits for the event after this many data
        # messages (mid-stream); the path is in write_held meanwhile.
        self.write_holds: dict[str, tuple[int, threading.Event]] = {}
        self.write_held: set[str] = set()
        # WriteFile calls in progress, and the most at one time.
        self.writes_running = 0
        self.most_writes_running = 0
        # ZipFiles fails with LIMIT_EXCEEDED over this many input bytes.
        self.zip_max_input_bytes: int | None = None
        # Spooled captures by ID, and "object storage" by presigned URL.
        self.captures: dict[str, bytes] = {}
        self.objects: dict[str, bytes] = {}
        self.upload_headers: list[dict[str, str]] = []
        # Managed images by ID (the bundle zip) and each VM's active slot.
        self.managed_images: dict[str, bytes] = {}
        # Active slot by (sandbox, mount).
        self.managed_active: dict[tuple[str, str], int] = {}
        # SwapManagedRequest.mount of each swapped VM, in order.
        self.swap_mounts: list[str] = []
        self._ids = itertools.count(1)
        # Execution IDs of every Cancel.
        self.cancel_calls: list[str] = []
        # Cancel and DeleteFile calls in order: (method, execution ID or path).
        self.daemon_calls: list[tuple[str, str]] = []
        # Cancel fails with this reason, and the execution goes on.
        self.cancel_error: SandboxDaemonErrorReason | None = None
        # Start and Run refuse with EXECUTION_CAP_REACHED at this many
        # running executions of a VM.
        self.max_running_executions = 64
        # Seconds each Create waits before it runs (to overlap two wakes).
        self.create_delay_seconds = 0.0
        # Like the real agent: a Create of a stopped (sandbox, attempt) fails
        # with STALE_ATTEMPT. Off by default.
        self.remember_stopped_attempts = False
        self.stopped_attempts: set[tuple[str, int]] = set()
        # ListFiles returns at most this many entries (None: 10,000).
        self.list_max_entries: int | None = None
        # ListFiles fails with RESOURCE_EXHAUSTED when its response has more
        # entries, as one over the gRPC message limit does.
        self.list_response_limit: int | None = None
        # The (path, recursive) of each ListFiles, in order.
        self.list_requests: list[tuple[str, bool]] = []
        # False: an older root drive whose daemon has no StatFiles.
        self.stat_files_supported = True
        # Seconds each Stop waits before it runs.
        self.stop_delay_seconds = 0.0
        # CaptureSession waits this long first; a cancelled call ends early
        # and spools nothing (like the agent).
        self.capture_delay_seconds = 0.0
        self.capture_started = threading.Event()
        self.capture_cancelled = threading.Event()
        self.drain_state = hostagent_pb2.DRAIN_STATE_ACTIVE
        # Seconds each guest daemon Init waits before it runs.
        self.init_delay_seconds = 0.0
        # Like grpc-go, the agent resets a stream with CANCELLED at its
        # deadline; this many seconds early models a reset that wins the race.
        self.stream_reset_lead_seconds: float | None = None

    def add_vm(
        self,
        *,
        sandbox_id: str,
        tenant_id: str,
        attempt: int,
        state: hostagent_pb2.VMState = hostagent_pb2.VM_STATE_RUNNING,
        daemon_key: str | None = None,
    ) -> hostagent_pb2.VM:
        with self.lock:
            if daemon_key is not None:
                self.daemon_keys[sandbox_id] = daemon_key
            self.next_generation += 1
            vm = hostagent_pb2.VM(
                sandbox_id=sandbox_id,
                attempt=attempt,
                generation=self.next_generation,
                template=self.templates[0].version,
                vcpus=2,
                mem_mib=self.templates[0].mem_mib,
                scratch_gib=4,
                state=state,
                pid=4242,
                tenant_id=tenant_id,
            )
            self.vms[sandbox_id] = vm
            return vm

    def Create(  # noqa: N802
        self, request: hostagent_pb2.CreateRequest, context: grpc.ServicerContext
    ) -> hostagent_pb2.CreateResponse:
        if self.create_delay_seconds:
            time.sleep(self.create_delay_seconds)
        with self.lock:
            self.create_calls += 1
            self.create_requests.append(
                (request.sandbox_id, request.attempt, request.sandboxd_key)
            )
            if self.refuse_create is not None and self.refuse_create_times != 0:
                if self.refuse_create_times is not None:
                    self.refuse_create_times -= 1
                abort_with_reason(context, self.refuse_create, "refused by the test")
            if (
                self.remember_stopped_attempts
                and (request.sandbox_id, request.attempt) in self.stopped_attempts
            ):
                abort_with_reason(
                    context, HostAgentErrorReason.STALE_ATTEMPT, "attempt stopped"
                )
            existing = self.vms.get(request.sandbox_id)
            if existing is not None:
                # Like the real agent: the same attempt returns the VM, even
                # an exited one; only a newer attempt replaces an exited VM.
                if existing.attempt == request.attempt:
                    if existing.state != hostagent_pb2.VM_STATE_EXITED:
                        self._install_key(context, request)
                    return hostagent_pb2.CreateResponse(vm=existing, created=False)
                if (
                    existing.state != hostagent_pb2.VM_STATE_EXITED
                    or request.attempt < existing.attempt
                ):
                    abort_with_reason(
                        context, HostAgentErrorReason.ATTEMPT_CONFLICT, "other attempt"
                    )
                del self.vms[request.sandbox_id]
            if all(t.version != request.template for t in self.templates):
                abort_with_reason(
                    context, HostAgentErrorReason.TEMPLATE_MISSING, "no template"
                )
            if self.mem_available_mib < request.mem_mib:
                abort_with_reason(
                    context, HostAgentErrorReason.CAPACITY_MEMORY, "not enough memory"
                )
            self.next_generation += 1
            vm = hostagent_pb2.VM(
                sandbox_id=request.sandbox_id,
                attempt=request.attempt,
                generation=self.next_generation,
                template=request.template,
                vcpus=request.vcpus,
                mem_mib=request.mem_mib,
                scratch_gib=request.scratch_gib,
                state=hostagent_pb2.VM_STATE_RUNNING,
                pid=4242,
                tenant_id=request.tenant_id,
            )
            self.vms[request.sandbox_id] = vm
            self.mem_available_mib -= request.mem_mib
            # A new VM boots a new daemon with no key and no Init.
            self.daemon_keys.pop(request.sandbox_id, None)
            self.daemon_inits.pop(request.sandbox_id, None)
            self._drop_guest_state(request.sandbox_id)
            if self.lost_create_answers > 0:
                self.lost_create_answers -= 1
                self.daemon_keys[request.sandbox_id] = request.sandboxd_key
                context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "answer lost")
            self._install_key(context, request)
            return hostagent_pb2.CreateResponse(vm=vm, created=True)

    def _install_key(
        self, context: grpc.ServicerContext, request: hostagent_pb2.CreateRequest
    ) -> None:
        """The agent's SetKey over vsock: the first key stays."""
        if not request.sandboxd_key:
            return
        if self.guest_unreachable_creates > 0:
            self.guest_unreachable_creates -= 1
            abort_with_reason(
                context, HostAgentErrorReason.GUEST_UNREACHABLE, "daemon not ready"
            )
        held = self.daemon_keys.setdefault(request.sandbox_id, request.sandboxd_key)
        if held != request.sandboxd_key:
            abort_with_reason(
                context, HostAgentErrorReason.GUEST_KEY_REJECTED, "KEY_ALREADY_SET"
            )

    def Stop(  # noqa: N802
        self, request: hostagent_pb2.StopRequest, context: grpc.ServicerContext
    ) -> hostagent_pb2.StopResponse:
        if self.stop_delay_seconds:
            time.sleep(self.stop_delay_seconds)
        with self.lock:
            self.stop_calls.append(
                (request.sandbox_id, request.attempt, request.generation)
            )
            vm = self.vms.get(request.sandbox_id)
            if vm is None:
                abort_with_reason(
                    context, HostAgentErrorReason.SANDBOX_NOT_FOUND, "no such VM"
                )
                raise AssertionError("unreachable")
            if vm.attempt != request.attempt or vm.generation != request.generation:
                abort_with_reason(
                    context, HostAgentErrorReason.INSTANCE_MISMATCH, "other instance"
                )
            del self.vms[request.sandbox_id]
            self.stopped_attempts.add((request.sandbox_id, vm.attempt))
            self.daemon_keys.pop(request.sandbox_id, None)
            self.daemon_inits.pop(request.sandbox_id, None)
            self._drop_guest_state(request.sandbox_id)
            self.mem_available_mib += vm.mem_mib
            return hostagent_pb2.StopResponse(already_stopped=False)

    def List(  # noqa: N802
        self,
        request: hostagent_pb2.ListRequest,  # noqa: ARG002
        context: grpc.ServicerContext,  # noqa: ARG002
    ) -> hostagent_pb2.ListResponse:
        with self.lock:
            self.list_calls += 1
            return hostagent_pb2.ListResponse(vms=list(self.vms.values()))

    def NodeInfo(  # noqa: N802
        self,
        request: hostagent_pb2.NodeInfoRequest,  # noqa: ARG002
        context: grpc.ServicerContext,  # noqa: ARG002
    ) -> hostagent_pb2.NodeInfoResponse:
        with self.lock:
            return hostagent_pb2.NodeInfoResponse(
                mem_total_mib=65_536,
                mem_available_mib=self.mem_available_mib,
                vm_count=len(self.vms),
                templates=self.templates,
                cpu_model="fake",
                firecracker_version="v1.17.0",
                host_kernel="6.18",
                agent_version="test",
                disk_free_mib=100_000,
                max_vms=self.max_vms,
                vm_slots_used=len(self.vms) + self.other_slots,
                drain=hostagent_pb2.DrainStatus(state=self.drain_state),
            )

    def CloseConnections(  # noqa: N802
        self,
        request: hostagent_pb2.CloseConnectionsRequest,  # noqa: ARG002
        context: grpc.ServicerContext,  # noqa: ARG002
    ) -> hostagent_pb2.CloseConnectionsResponse:
        return hostagent_pb2.CloseConnectionsResponse(closed=3)

    def next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids)}"

    def _drop_guest_state(self, sandbox_id: str) -> None:
        """A new or stopped VM has none of the old guest's executions or files.
        Call with the lock held."""
        for execution in self.executions.pop(sandbox_id, {}).values():
            execution.vm_gone = True
        self.ended.notify_all()
        for slot_key in [k for k in self.managed_active if k[0] == sandbox_id]:
            del self.managed_active[slot_key]
        for key in [k for k in self.files if k[0] == sandbox_id]:
            del self.files[key]
            self.file_modes.pop(key, None)
            self.file_times.pop(key, None)
        for key in [k for k in self.links if k[0] == sandbox_id]:
            del self.links[key]

    def _check_instance(
        self,
        context: grpc.ServicerContext,
        sandbox_id: str,
        attempt: int,
        generation: int,
        sandboxd_key: str,
    ) -> None:
        vm = self.vms.get(sandbox_id)
        if vm is None:
            abort_with_reason(
                context, HostAgentErrorReason.SANDBOX_NOT_FOUND, "no such VM"
            )
            raise AssertionError("unreachable")
        if vm.attempt != attempt or vm.generation != generation:
            abort_with_reason(
                context, HostAgentErrorReason.INSTANCE_MISMATCH, "other instance"
            )
        if self.daemon_keys.get(sandbox_id) != sandboxd_key:
            abort_daemon(context, SandboxDaemonErrorReason.UNAUTHENTICATED, "bad key")

    def CaptureSession(  # noqa: N802
        self,
        request: hostagent_pb2.CaptureSessionRequest,
        context: grpc.ServicerContext,
    ) -> hostagent_pb2.CaptureSessionResponse:
        self.capture_started.set()
        waited_until = time.monotonic() + self.capture_delay_seconds
        while time.monotonic() < waited_until:
            if not context.is_active():
                self.capture_cancelled.set()
                abort_with_reason(context, HostAgentErrorReason.INTERNAL, "cancelled")
            time.sleep(0.05)
        with self.lock:
            self._check_instance(
                context,
                request.sandbox_id,
                request.attempt,
                request.generation,
                request.sandboxd_key,
            )
            roots = list(request.roots) or ["attachments"]
            exclude = set(request.exclude_names) or {"node_modules"}
            selected = {
                path: data
                for (sid, session, path), data in self.files.items()
                if sid == request.sandbox_id
                and session == request.session_id
                and path.split("/", 1)[0] in roots
            }
            members = {
                path: data
                for path, data in selected.items()
                if not _skipped(path, exclude, skip_hidden=False)
            }
            # Like the daemon: top-level files go under TOP_FILES_ROOT. Files
            # directly in a TOP_FILES_ROOT directory stay there, unless a
            # top-level entry has the same name.
            top_names = {
                p.split("/", 1)[0]
                for (sid, session, p) in self.files
                if sid == request.sandbox_id and session == request.session_id
            }
            members = {
                p if "/" in p else f"{TOP_FILES_ROOT}/{p}": d
                for p, d in members.items()
                if not p.startswith(f"{TOP_FILES_ROOT}/")
                or (
                    p.count("/") == 1
                    and p.removeprefix(f"{TOP_FILES_ROOT}/") not in top_names
                )
            }
            archive = _zip(members)
            capture_id = self.next_id("cap")
            self.captures[capture_id] = archive
            response = hostagent_pb2.CaptureSessionResponse(
                capture_id=capture_id,
                size_bytes=len(archive),
                sha256=hashlib.sha256(archive).hexdigest(),
                files=len(members),
                expanded_bytes=sum(len(d) for d in members.values()),
                excluded=len(selected) - len(members),
                roots=sorted({p.split("/", 1)[0] for p in members}),
            )
            response.expires_at.GetCurrentTime()
            return response

    def UploadCapture(  # noqa: N802
        self, request: hostagent_pb2.UploadCaptureRequest, context: grpc.ServicerContext
    ) -> hostagent_pb2.UploadCaptureResponse:
        with self.lock:
            archive = self.captures.get(request.capture_id)
            if archive is None:
                abort_with_reason(
                    context, HostAgentErrorReason.CAPTURE_NOT_FOUND, "no capture"
                )
                raise AssertionError("unreachable")
            if request.request.method != "PUT":
                abort_with_reason(
                    context, HostAgentErrorReason.TRANSFER_FAILED, "not a PUT"
                )
            length = {k.lower(): v for k, v in request.request.headers.items()}.get(
                "content-length"
            )
            if length is not None and length != str(len(archive)):
                abort_with_reason(
                    context, HostAgentErrorReason.ARCHIVE_MISMATCH, "Content-Length"
                )
            self.objects[request.request.url] = archive
            self.upload_headers.append(dict(request.request.headers))
            del self.captures[request.capture_id]
            return hostagent_pb2.UploadCaptureResponse(
                size_bytes=len(archive),
                sha256=hashlib.sha256(archive).hexdigest(),
                http_status=200,
                etag='"fake"',
            )

    def DiscardCapture(  # noqa: N802
        self,
        request: hostagent_pb2.DiscardCaptureRequest,
        context: grpc.ServicerContext,  # noqa: ARG002
    ) -> hostagent_pb2.DiscardCaptureResponse:
        with self.lock:
            found = self.captures.pop(request.capture_id, None) is not None
            return hostagent_pb2.DiscardCaptureResponse(discarded=found)

    def RestoreSession(  # noqa: N802
        self,
        request: hostagent_pb2.RestoreSessionRequest,
        context: grpc.ServicerContext,
    ) -> hostagent_pb2.RestoreSessionResponse:
        with self.lock:
            self._check_instance(
                context,
                request.sandbox_id,
                request.attempt,
                request.generation,
                request.sandboxd_key,
            )
            archive = self.objects.get(request.request.url)
            if archive is None or request.request.method != "GET":
                abort_with_reason(
                    context, HostAgentErrorReason.TRANSFER_FAILED, "GET failed"
                )
                raise AssertionError("unreachable")
            if (
                len(archive) != request.size_bytes
                or hashlib.sha256(archive).hexdigest() != request.sha256
            ):
                abort_with_reason(
                    context, HostAgentErrorReason.ARCHIVE_MISMATCH, "other archive"
                )
            archived = _unzip(archive)
            members = {
                p.removeprefix(f"{TOP_FILES_ROOT}/"): d for p, d in archived.items()
            }
            roots = {p.split("/", 1)[0] for p in members}
            for key in [
                k
                for k in self.files
                if k[:2] == (request.sandbox_id, request.session_id)
                and k[2].split("/", 1)[0] in roots
            ]:
                del self.files[key]
            for path, data in members.items():
                self.files[(request.sandbox_id, request.session_id, path)] = data
            return hostagent_pb2.RestoreSessionResponse(
                files=len(members),
                expanded_bytes=sum(len(d) for d in members.values()),
                roots=sorted({p.split("/", 1)[0] for p in archived}),
            )

    def PutManagedImage(  # noqa: N802
        self,
        request_iterator: Iterator[hostagent_pb2.PutManagedImageRequest],
        context: grpc.ServicerContext,
    ) -> hostagent_pb2.PutManagedImageResponse:
        first = next(request_iterator)
        if first.WhichOneof("part") != "header":
            abort_with_reason(
                context, HostAgentErrorReason.INVALID_ARGUMENT, "header first"
            )
        header = first.header
        data = b"".join(r.data for r in request_iterator)
        try:
            files = _unzip(data)
        except zipfile.BadZipFile:
            files = None
        if (
            files is None
            or len(data) != header.size_bytes
            or hashlib.sha256(data).hexdigest() != header.sha256
        ):
            abort_with_reason(
                context, HostAgentErrorReason.MANAGED_BUNDLE_INVALID, "bad bundle"
            )
            raise AssertionError("unreachable")
        with self.lock:
            built = header.sha256 not in self.managed_images
            self.managed_images[header.sha256] = data
            image = hostagent_pb2.ManagedImageInfo(
                image_id=header.sha256,
                size_bytes=len(data),
                fs_uuid="00000000-0000-4000-8000-000000000000",
                files=len(files),
            )
            return hostagent_pb2.PutManagedImageResponse(image=image, built=built)

    def SwapManaged(  # noqa: N802
        self, request: hostagent_pb2.SwapManagedRequest, context: grpc.ServicerContext
    ) -> hostagent_pb2.SwapManagedResponse:
        with self.lock:
            if request.image_id not in self.managed_images:
                abort_with_reason(
                    context, HostAgentErrorReason.MANAGED_IMAGE_MISSING, "no image"
                )
            results = []
            for t in request.targets:
                vm = self.vms.get(t.sandbox_id)
                if vm is None or (vm.attempt, vm.generation) != (
                    t.attempt,
                    t.generation,
                ):
                    results.append(
                        hostagent_pb2.SwapResult(
                            sandbox_id=t.sandbox_id,
                            ok=False,
                            reason=hostagent_pb2.INSTANCE_MISMATCH,
                            message="other instance",
                        )
                    )
                    continue
                if self.daemon_keys.get(t.sandbox_id) != t.sandboxd_key:
                    results.append(
                        hostagent_pb2.SwapResult(
                            sandbox_id=t.sandbox_id,
                            ok=False,
                            reason=hostagent_pb2.GUEST_KEY_REJECTED,
                            message="guest daemon: bad key",
                        )
                    )
                    continue
                slot_key = (t.sandbox_id, request.mount or "skills")
                active = (
                    hostagent_pb2.MANAGED_SLOT_A
                    if self.managed_active.get(slot_key) == hostagent_pb2.MANAGED_SLOT_B
                    else hostagent_pb2.MANAGED_SLOT_B
                )
                self.managed_active[slot_key] = active
                self.swap_mounts.append(request.mount)
                results.append(
                    hostagent_pb2.SwapResult(
                        sandbox_id=t.sandbox_id, ok=True, active=active, changed=True
                    )
                )
            return hostagent_pb2.SwapManagedResponse(results=results)


# A write_failures key that matches every path without its own entry.
ANY_PATH = "*"


class WriteFailure:
    """WriteFile fails with `reason` after all data arrived, and stores
    nothing: the next `count` times (None: every time). A status code
    `reason` fails the call with no daemon reason, as a deadline does."""

    def __init__(
        self,
        reason: SandboxDaemonErrorReason | grpc.StatusCode,
        count: int | None = None,
    ) -> None:
        self.reason = reason
        self.count = count


@dataclass
class FakeExecution:
    """A scripted command: echo, fail <code>, cat (echoes stdin), sleep,
    mkdir, seq <n>, soffice (a PDF of any existing source) or pdftoppm (a
    FAKE_JPEG of a source that starts with "%PDF"). `bash -c <script>` runs
    the script's words as one of these."""

    execution_id: str
    argv: list[str]
    labels: dict[str, str]
    stdin_open: bool
    session_id: str = ""
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    stdout: bytes = b""
    stderr: bytes = b""
    result: sandboxd_pb2.ExecResult | None = None
    # The daemon dropped the bytes before these offsets.
    stdout_kept_from: int = 0
    stderr_kept_from: int = 0
    stdin_data: bytearray = field(default_factory=bytearray)
    # The VM stopped: open streams of the execution break.
    vm_gone: bool = False
    # The CancelSignal of a SIGINT or SIGTERM cancel.
    signaled: int = 0

    def end(self, completion: sandboxd_pb2.Completion, exit_code: int = -1) -> None:
        self.stdin_open = False
        self.result = sandboxd_pb2.ExecResult(
            completion=completion,
            exit_code=exit_code,
            stdout_bytes=len(self.stdout),
            stderr_bytes=len(self.stderr),
        )
        self.result.finished_at.GetCurrentTime()

    def record(self) -> sandboxd_pb2.Execution:
        record = sandboxd_pb2.Execution(
            execution_id=self.execution_id,
            state=sandboxd_pb2.ENDED if self.result else sandboxd_pb2.RUNNING,
            argv=self.argv,
            labels=self.labels,
            pid=77,
            stdout_bytes=len(self.stdout),
            stderr_bytes=len(self.stderr),
        )
        if self.result is not None:
            record.result.CopyFrom(self.result)
        return record


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(members):
            zf.writestr(path, members[path])
    return buf.getvalue()


def _unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _skipped(path: str, exclude: set[str], *, skip_hidden: bool) -> bool:
    parts = path.split("/")
    return bool(exclude & set(parts)) or (
        skip_hidden and any(p.startswith(".") for p in parts)
    )


def _vm_file_key(sandbox_id: str, path: str) -> tuple[str, str, str]:
    """The `files` key of an absolute path that a command names: a session
    file under WORKSPACES, else a VM file."""
    session, _, rel = path.removeprefix(WORKSPACES + "/").partition("/")
    if path.startswith(WORKSPACES + "/") and rel:
        return sandbox_id, session, rel
    return sandbox_id, "", path


class FakeSandboxd(sandboxd_pb2_grpc.SandboxdServicer):
    """The guest daemons behind the agent pass-through (x-sandbox-id routing)."""

    def __init__(self, agent: FakeHostAgent) -> None:
        self.agent = agent

    def _route(self, context: grpc.ServicerContext) -> tuple[str, str | None]:
        md = dict(context.invocation_metadata())
        sandbox_id = md.get(SANDBOX_ID_HEADER)
        if not isinstance(sandbox_id, str):
            abort_with_reason(
                context, HostAgentErrorReason.INVALID_ARGUMENT, "no x-sandbox-id"
            )
            raise AssertionError("unreachable")
        vm = self.agent.vms.get(sandbox_id)
        if vm is None or vm.state != hostagent_pb2.VM_STATE_RUNNING:
            abort_with_reason(
                context, HostAgentErrorReason.VM_NOT_RUNNING, "no running VM"
            )
        key = md.get(SANDBOXD_KEY_HEADER)
        return sandbox_id, key if isinstance(key, str) else None

    def _check_key(
        self, context: grpc.ServicerContext, sandbox_id: str, key: str | None
    ) -> None:
        held = self.agent.daemon_keys.get(sandbox_id)
        if held is None:
            abort_daemon(context, SandboxDaemonErrorReason.KEY_NOT_SET, "no key")
        if key != held:
            abort_daemon(context, SandboxDaemonErrorReason.UNAUTHENTICATED, "bad key")

    def Health(  # noqa: N802
        self,
        request: sandboxd_pb2.HealthRequest,  # noqa: ARG002
        context: grpc.ServicerContext,
    ) -> sandboxd_pb2.HealthResponse:
        with self.agent.lock:
            sandbox_id, _ = self._route(context)
            generation = self.agent.daemon_inits.get(sandbox_id)
            return sandboxd_pb2.HealthResponse(
                version="fake",
                sandbox_id=sandbox_id,
                key_set=sandbox_id in self.agent.daemon_keys,
                initialized=generation is not None,
                generation=generation or 0,
                running_executions=sum(
                    1
                    for e in self.agent.executions.get(sandbox_id, {}).values()
                    if e.result is None
                ),
            )

    def SetKey(  # noqa: N802
        self,
        request: sandboxd_pb2.SetKeyRequest,  # noqa: ARG002
        context: grpc.ServicerContext,
    ) -> sandboxd_pb2.SetKeyResponse:
        abort_with_reason(
            context, HostAgentErrorReason.METHOD_NOT_ALLOWED, "only the agent"
        )
        raise AssertionError("unreachable")

    def Init(  # noqa: N802
        self, request: sandboxd_pb2.InitRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.InitResponse:
        if self.agent.init_delay_seconds:
            time.sleep(self.agent.init_delay_seconds)
        with self.agent.lock:
            sandbox_id, key = self._route(context)
            self._check_key(context, sandbox_id, key)
            self.agent.init_requests.append((request, sandbox_id))
            self.agent.daemon_inits[sandbox_id] = request.generation
            return sandboxd_pb2.InitResponse(
                version="fake", attached=True, relay_reset=True
            )

    def _ready(self, context: grpc.ServicerContext) -> str:
        """Route, check the key and Init. Call with the agent lock held."""
        sandbox_id, key = self._route(context)
        self._check_key(context, sandbox_id, key)
        if sandbox_id not in self.agent.daemon_inits:
            abort_daemon(context, SandboxDaemonErrorReason.NOT_INITIALIZED, "no Init")
        return sandbox_id

    # Exec.

    def _start(
        self, context: grpc.ServicerContext, command: sandboxd_pb2.Command
    ) -> FakeExecution:
        sandbox_id = self._ready(context)
        argv = list(command.argv)
        script = argv
        if argv[:2] == ["bash", "-c"] and len(argv) == 3:
            script = shlex.split(argv[2])
        if not script or script[0] not in (
            "say",
            "echo",
            "fail",
            "cat",
            "sleep",
            "mkdir",
            "true",
            "seq",
            "python3",
            "soffice",
            "pdftoppm",
        ):
            abort_daemon(context, SandboxDaemonErrorReason.START_FAILED, "no program")
        running = [
            e
            for e in self.agent.executions.get(sandbox_id, {}).values()
            if e.result is None
        ]
        if len(running) >= self.agent.max_running_executions:
            abort_daemon(context, SandboxDaemonErrorReason.EXECUTION_CAP_REACHED, "cap")
        execution = FakeExecution(
            execution_id=self.agent.next_id("exec"),
            argv=argv,
            labels=dict(command.labels),
            stdin_open=command.stdin,
            session_id=command.session_id,
            cwd=command.cwd,
            env=dict(command.env),
        )
        argv = script
        if argv[0] in ("mkdir", "true"):
            execution.end(sandboxd_pb2.EXITED, 0)
        elif argv[0] == "echo":
            execution.stdout = (" ".join(argv[1:]) + "\n").encode()
            execution.end(sandboxd_pb2.EXITED, 0)
        elif argv[0] == "seq":
            execution.stdout = "".join(
                f"{n}\n" for n in range(1, int(argv[1]) + 1)
            ).encode()
            execution.end(sandboxd_pb2.EXITED, 0)
        elif argv[0] == "say":
            # Prints its arguments, then runs until it is killed.
            execution.stdout = (" ".join(argv[1:]) + "\n").encode()
        elif argv[0] == "fail":
            execution.stderr = b"failed\n"
            execution.end(sandboxd_pb2.EXITED, int(argv[1]))
        elif argv[0] == "python3":
            code, execution.stderr = self._run_python(sandbox_id, argv[1:])
            execution.end(sandboxd_pb2.EXITED, code)
        elif argv[0] == "soffice":
            # Like LibreOffice: exit 0 even when the source does not load.
            outdir = argv[argv.index("--outdir") + 1]
            source = self.agent.files.get(_vm_file_key(sandbox_id, argv[-1]))
            if source is not None:
                stem = posixpath.splitext(posixpath.basename(argv[-1]))[0]
                self.agent.files[(sandbox_id, "", f"{outdir}/{stem}.pdf")] = (
                    b"%PDF-" + source
                )
            execution.end(sandboxd_pb2.EXITED, 0)
        elif argv[0] == "pdftoppm":
            source = self.agent.files.get(_vm_file_key(sandbox_id, argv[-2]))
            if source is None or not source.startswith(b"%PDF"):
                execution.stderr = b"Syntax Error: Couldn't read xref table\n"
                execution.end(sandboxd_pb2.EXITED, 1)
            else:
                self.agent.files[(sandbox_id, "", f"{argv[-1]}.jpg")] = FAKE_JPEG
                execution.end(sandboxd_pb2.EXITED, 0)
        self.agent.executions.setdefault(sandbox_id, {})[execution.execution_id] = (
            execution
        )
        return execution

    def _run_python(self, sandbox_id: str, args: list[str]) -> tuple[int, bytes]:
        """`-I -c <code> <file> <dir> ...`: runs the code with real Python on a
        local copy of the VM file and directory, then copies the results back.
        Call with the lock held."""
        flag, dash_c, code, src, root, *rest = args
        if (flag, dash_c) != ("-I", "-c"):
            return 2, b"unsupported python3 call\n"
        with tempfile.TemporaryDirectory() as tmp:
            local_src = posixpath.join(tmp, "src")
            local_root = posixpath.join(tmp, "root")
            src_key = (sandbox_id, "", src)
            if src_key in self.agent.files:
                with open(local_src, "wb") as f:
                    f.write(self.agent.files[src_key])
            under_root = [
                key
                for key in self.agent.files
                if key[0] == sandbox_id
                and key[1] == ""
                and key[2].startswith(root + "/")
            ]
            for key in under_root:
                local = posixpath.join(local_root, key[2].removeprefix(root + "/"))
                os.makedirs(posixpath.dirname(local), exist_ok=True)
                with open(local, "wb") as f:
                    f.write(self.agent.files[key])
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code, local_src, local_root, *rest],
                capture_output=True,
                timeout=60,
            )
            for key in under_root:
                del self.agent.files[key]
            for directory, _, names in os.walk(local_root):
                for name in names:
                    local = posixpath.join(directory, name)
                    rel = posixpath.relpath(local, local_root)
                    with open(local, "rb") as f:
                        self.agent.files[(sandbox_id, "", f"{root}/{rel}")] = f.read()
            if not os.path.exists(local_src):
                self.agent.files.pop(src_key, None)
        return proc.returncode, proc.stderr

    def _stat(self, key: tuple[str, str, str]) -> sandboxd_pb2.PathStat:
        """The canned facts of a path, else those of its own entry. Call
        with the lock held."""
        canned = self.agent.path_stats.get(key)
        if canned is not None:
            return canned
        sandbox_id, session_id, rel = key
        target = self.agent.links.get(key)
        if target is not None:
            return sandboxd_pb2.PathStat(
                exists=True,
                type=sandboxd_pb2.FILE_TYPE_SYMLINK,
                mode=0o777,
                link_target=target,
                target_error=sandboxd_pb2.STAT_ERROR_MISSING,
            )
        if key in self.agent.files:
            kind, mode = (
                sandboxd_pb2.FILE_TYPE_REGULAR,
                self.agent.file_modes.get(key, 0o644),
            )
        elif rel == "." or any(
            k[:2] == (sandbox_id, session_id) and k[2].startswith(rel + "/")
            for k in itertools.chain(self.agent.files, self.agent.links)
        ):
            kind, mode = sandboxd_pb2.FILE_TYPE_DIRECTORY, 0o755
        else:
            return sandboxd_pb2.PathStat(target_error=sandboxd_pb2.STAT_ERROR_MISSING)
        return sandboxd_pb2.PathStat(
            exists=True,
            type=kind,
            mode=mode,
            target_type=kind,
            target_mode=mode,
            # A stable identity per entry of the fake.
            device=1,
            inode=zlib.crc32(rel.encode()) + 1,
        )

    def StatFiles(  # noqa: N802
        self, request: sandboxd_pb2.StatFilesRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.StatFilesResponse:
        with self.agent.lock:
            sandbox_id = self._ready(context)
            if not self.agent.stat_files_supported:
                context.abort(grpc.StatusCode.UNIMPLEMENTED, "unknown method")
            stats: list[sandboxd_pb2.PathStat] = []
            for path in request.paths:
                rel = self._check_path(context, path) if path.strip("/.") else "."
                stat = sandboxd_pb2.PathStat()
                stat.CopyFrom(self._stat((sandbox_id, request.session_id, rel)))
                stat.path = rel
                stats.append(stat)
            return sandboxd_pb2.StatFilesResponse(stats=stats)

    def _execution(
        self, context: grpc.ServicerContext, execution_id: str
    ) -> FakeExecution:
        sandbox_id = self._ready(context)
        execution = self.agent.executions.get(sandbox_id, {}).get(execution_id)
        if execution is None:
            abort_daemon(
                context, SandboxDaemonErrorReason.EXECUTION_NOT_FOUND, "no record"
            )
            raise AssertionError("unreachable")
        return execution

    @staticmethod
    def _events(
        execution: FakeExecution, stdout_offset: int, stderr_offset: int
    ) -> list[sandboxd_pb2.ExecEvent]:
        """Output from the offsets, then the result (ended executions only)."""
        events: list[sandboxd_pb2.ExecEvent] = []
        for stream, data, kept_from, offset in (
            (
                sandboxd_pb2.STDOUT,
                execution.stdout,
                execution.stdout_kept_from,
                stdout_offset,
            ),
            (
                sandboxd_pb2.STDERR,
                execution.stderr,
                execution.stderr_kept_from,
                stderr_offset,
            ),
        ):
            if offset < kept_from:
                gap = sandboxd_pb2.OutputGap(stream=stream, to=kept_from)
                setattr(gap, "from", offset)
                events.append(sandboxd_pb2.ExecEvent(gap=gap))
                offset = kept_from
            # In chunks of at most the daemon's chunk size.
            events.extend(
                sandboxd_pb2.ExecEvent(
                    output=sandboxd_pb2.OutputChunk(
                        stream=stream,
                        offset=start,
                        data=data[start : start + _STREAM_CHUNK_BYTES],
                    )
                )
                for start in range(offset, len(data), _STREAM_CHUNK_BYTES)
            )
        if execution.result is not None:
            events.append(sandboxd_pb2.ExecEvent(result=execution.result))
        return events

    def Run(  # noqa: N802
        self, request: sandboxd_pb2.RunRequest, context: grpc.ServicerContext
    ) -> Iterator[sandboxd_pb2.ExecEvent]:
        with self.agent.lock:
            execution = self._start(context, request.command)
            started = sandboxd_pb2.ExecStarted(
                execution_id=execution.execution_id, pid=77
            )
            started.started_at.GetCurrentTime()
        yield sandboxd_pb2.ExecEvent(started=started)
        yield from self._until_ended(context, execution, 0, 0)

    def _until_ended(
        self,
        context: grpc.ServicerContext,
        execution: FakeExecution,
        stdout_offset: int,
        stderr_offset: int,
    ) -> Iterator[sandboxd_pb2.ExecEvent]:
        """Like the daemon: output as it comes, then the result. A client
        that goes away ends the stream, not the command."""
        offsets = [stdout_offset, stderr_offset]
        reset_lead = self.agent.stream_reset_lead_seconds
        while True:
            with self.agent.lock:
                while (
                    execution.result is None
                    and not execution.vm_gone
                    and context.is_active()
                    and len(execution.stdout) <= offsets[0]
                    and len(execution.stderr) <= offsets[1]
                ):
                    if (
                        reset_lead is not None
                        and context.time_remaining() <= reset_lead
                    ):
                        context.abort(
                            grpc.StatusCode.CANCELLED,
                            "Received RST_STREAM with error code 8",
                        )
                    self.agent.ended.wait(timeout=0.05)
                if execution.vm_gone:
                    abort_with_reason(
                        context, HostAgentErrorReason.VM_NOT_RUNNING, "VM stopped"
                    )
                if not context.is_active():
                    return
                events = self._events(execution, offsets[0], offsets[1])
                offsets = [
                    max(offsets[0], len(execution.stdout)),
                    max(offsets[1], len(execution.stderr)),
                ]
                done = execution.result is not None
            yield from events
            if done:
                return

    def Start(  # noqa: N802
        self, request: sandboxd_pb2.StartRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.StartResponse:
        with self.agent.lock:
            execution = self._start(context, request.command)
            return sandboxd_pb2.StartResponse(
                started=sandboxd_pb2.ExecStarted(
                    execution_id=execution.execution_id, pid=77
                )
            )

    def Stream(  # noqa: N802
        self, request: sandboxd_pb2.StreamRequest, context: grpc.ServicerContext
    ) -> Iterator[sandboxd_pb2.ExecEvent]:
        with self.agent.lock:
            execution = self._execution(context, request.execution_id)
        yield from self._until_ended(
            context, execution, request.stdout_offset, request.stderr_offset
        )

    def Interact(  # noqa: N802
        self, request: sandboxd_pb2.InteractRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.InteractResponse:
        with self.agent.lock:
            execution = self._execution(context, request.execution_id)
            if execution.result is not None:
                abort_daemon(context, SandboxDaemonErrorReason.EXECUTION_ENDED, "ended")
            if not execution.stdin_open:
                abort_daemon(
                    context, SandboxDaemonErrorReason.STDIN_NOT_OPEN, "no stdin"
                )
            execution.stdin_data += request.data
            if execution.argv[-1:] == ["cat"]:
                # cat: echo stdin as it comes, exit at EOF.
                execution.stdout = bytes(execution.stdin_data)
            if request.close_stdin:
                execution.end(sandboxd_pb2.EXITED, 0)
            self.agent.ended.notify_all()
            return sandboxd_pb2.InteractResponse(written=len(request.data))

    def Cancel(  # noqa: N802
        self, request: sandboxd_pb2.CancelRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.CancelResponse:
        with self.agent.lock:
            execution = self._execution(context, request.execution_id)
            self.agent.cancel_calls.append(request.execution_id)
            self.agent.daemon_calls.append(("Cancel", request.execution_id))
            if self.agent.cancel_error is not None:
                abort_daemon(context, self.agent.cancel_error, "cancel failed")
            already_ended = execution.result is not None
            soft = request.signal in (
                sandboxd_pb2.CANCEL_SIGNAL_SIGINT,
                sandboxd_pb2.CANCEL_SIGNAL_SIGTERM,
            )
            if soft and not already_ended:
                # Scripted commands do not trap signals: the command dies of
                # it after the answer, which carries no result.
                execution.signaled = request.signal
                execution.end(sandboxd_pb2.CANCELED)
                self.agent.ended.notify_all()
                return sandboxd_pb2.CancelResponse(signaled=True)
            if not already_ended:
                execution.end(sandboxd_pb2.CANCELED)
                self.agent.ended.notify_all()
            assert execution.result is not None
            return sandboxd_pb2.CancelResponse(
                result=execution.result, already_ended=already_ended
            )

    def Inspect(  # noqa: N802
        self, request: sandboxd_pb2.InspectRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.InspectResponse:
        with self.agent.lock:
            execution = self._execution(context, request.execution_id)
            return sandboxd_pb2.InspectResponse(execution=execution.record())

    def List(  # noqa: N802
        self, request: sandboxd_pb2.ListRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.ListResponse:
        with self.agent.lock:
            sandbox_id = self._ready(context)
            want = dict(request.labels)
            return sandboxd_pb2.ListResponse(
                executions=[
                    e.record()
                    for e in self.agent.executions.get(sandbox_id, {}).values()
                    if want.items() <= e.labels.items()
                ]
            )

    # Files: an in-memory tree of regular files and symlinks; directories
    # are implied.

    @staticmethod
    def _check_path(context: grpc.ServicerContext, path: str) -> str:
        if path.startswith("/") or ".." in path.split("/"):
            abort_daemon(context, SandboxDaemonErrorReason.INVALID_ARGUMENT, "bad path")
        return path.strip("/")

    def _file_key(
        self, context: grpc.ServicerContext, sandbox_id: str, session_id: str, path: str
    ) -> tuple[str, str, str]:
        """The `files` key of a call's path: session-relative with a session
        ID, else absolute and cleaned as the daemon's vmPath does (in the
        fake, a separate file even when it names a session directory)."""
        if session_id:
            return sandbox_id, session_id, self._check_path(context, path)
        # normpath keeps a leading "//"; path.Clean does not.
        normalized = "/" + posixpath.normpath(path).lstrip("/")
        if (
            not posixpath.isabs(path)
            or normalized == "/"
            or any(
                normalized == denied or normalized.startswith(denied + "/")
                for denied in _DENIED_VM_PATHS
            )
        ):
            abort_daemon(
                context, SandboxDaemonErrorReason.INVALID_ARGUMENT, "bad VM path"
            )
        return sandbox_id, "", normalized

    def _session_files(self, sandbox_id: str, session_id: str) -> dict[str, bytes]:
        return {
            path: data
            for (sid, session, path), data in self.agent.files.items()
            if sid == sandbox_id and session == session_id
        }

    @staticmethod
    def _info(
        path: str,
        size: int,
        *,
        directory: bool = False,
        mode: int = 0o644,
        modified_at: float | None = None,
    ) -> sandboxd_pb2.FileInfo:
        info = sandboxd_pb2.FileInfo(
            path=path,
            name=path.rsplit("/", 1)[-1],
            type=sandboxd_pb2.FILE_TYPE_DIRECTORY
            if directory
            else sandboxd_pb2.FILE_TYPE_REGULAR,
            size=size,
            mode=0o755 if directory else mode,
        )
        if modified_at is not None:
            info.modified_at.FromNanoseconds(int(modified_at * 1e9))
        return info

    def _followed(
        self, context: grpc.ServicerContext, key: tuple[str, str, str]
    ) -> tuple[str, str, str]:
        """The file a path names through its links, inside the session
        directory as the daemon's root confines it. Call with the lock held."""
        for _ in range(40):
            target = self.agent.links.get(key)
            if target is None:
                return key
            joined = posixpath.normpath(
                posixpath.join(posixpath.dirname(key[2]), target)
            )
            if posixpath.isabs(target) or joined.startswith(".."):
                abort_daemon(
                    context, SandboxDaemonErrorReason.INVALID_ARGUMENT, "escapes"
                )
            key = (key[0], key[1], joined)
        abort_daemon(context, SandboxDaemonErrorReason.INVALID_ARGUMENT, "loop")
        raise AssertionError("unreachable")

    def _parents_followed(
        self, context: grpc.ServicerContext, key: tuple[str, str, str]
    ) -> tuple[str, str, str]:
        """`key` with the links on its parent directories followed, as the
        daemon's root resolves a session path. Call with the lock held."""
        if not key[1]:
            return key
        *parents, name = key[2].split("/")
        resolved = ""
        for part in parents:
            joined = f"{resolved}/{part}" if resolved else part
            resolved = self._followed(context, (key[0], key[1], joined))[2]
        return key[0], key[1], f"{resolved}/{name}" if resolved else name

    def ReadFile(  # noqa: N802
        self, request: sandboxd_pb2.ReadFileRequest, context: grpc.ServicerContext
    ) -> Iterator[sandboxd_pb2.ReadFileResponse]:
        with self.agent.lock:
            sandbox_id = self._ready(context)
            key = self._file_key(context, sandbox_id, request.session_id, request.path)
            path = key[2]
            key = self._followed(context, key)
            data = self.agent.files.get(key)
            if data is None:
                below = "" if key[2] in ("", ".") else key[2].rstrip("/") + "/"
                if any(
                    k[:2] == key[:2] and k[2].startswith(below)
                    for k in self.agent.files
                ):
                    abort_daemon(
                        context,
                        SandboxDaemonErrorReason.INVALID_ARGUMENT,
                        f"{path} is not a regular file",
                    )
                abort_daemon(context, SandboxDaemonErrorReason.FILE_NOT_FOUND, path)
                raise AssertionError("unreachable")
            mode = self.agent.file_modes.get(key, 0o644)
        end = request.offset + request.length if request.length else len(data)
        body = data[request.offset : end]
        yield sandboxd_pb2.ReadFileResponse(info=self._info(path, len(data), mode=mode))
        for start in range(0, len(body), 64 << 10):
            yield sandboxd_pb2.ReadFileResponse(data=body[start : start + (64 << 10)])

    def _store(
        self,
        context: grpc.ServicerContext,
        sandbox_id: str,
        session_id: str,
        path: str,
        data: bytes,
        header: sandboxd_pb2.WriteFileHeader | sandboxd_pb2.UploadFileHeader,
    ) -> str:
        if len(data) != header.size or (
            header.sha256 and hashlib.sha256(data).hexdigest() != header.sha256
        ):
            abort_daemon(
                context, SandboxDaemonErrorReason.INVALID_ARGUMENT, "size or sha256"
            )
        key = (sandbox_id, session_id, path)
        self.agent.files[key] = data
        # A write replaces a link, as the daemon's rename does.
        self.agent.links.pop(key, None)
        mode = header.mode if isinstance(header, sandboxd_pb2.WriteFileHeader) else 0
        self.agent.file_modes[key] = mode or 0o644
        self.agent.file_times[key] = time.time()
        return hashlib.sha256(data).hexdigest()

    def WriteFile(  # noqa: N802
        self,
        request_iterator: Iterator[sandboxd_pb2.WriteFileRequest],
        context: grpc.ServicerContext,
    ) -> sandboxd_pb2.WriteFileResponse:
        with self.agent.lock:
            self.agent.writes_running += 1
            self.agent.most_writes_running = max(
                self.agent.most_writes_running, self.agent.writes_running
            )
        try:
            return self._write_file(request_iterator, context)
        finally:
            with self.agent.lock:
                self.agent.writes_running -= 1

    def _write_file(
        self,
        request_iterator: Iterator[sandboxd_pb2.WriteFileRequest],
        context: grpc.ServicerContext,
    ) -> sandboxd_pb2.WriteFileResponse:
        first = next(request_iterator)
        if first.WhichOneof("part") != "header":
            abort_daemon(
                context, SandboxDaemonErrorReason.INVALID_ARGUMENT, "header first"
            )
        header = first.header
        sizes: list[int] = []
        parts: list[bytes] = []
        hold = self.agent.write_holds.get(header.path)
        for request in request_iterator:
            sizes.append(len(request.data))
            parts.append(request.data)
            if hold is not None and len(sizes) == hold[0]:
                with self.agent.lock:
                    self.agent.write_held.add(header.path)
                hold[1].wait()
                with self.agent.lock:
                    self.agent.write_held.discard(header.path)
        data = b"".join(parts)
        gate = self.agent.write_gates.get(header.path)
        if gate is not None:
            with self.agent.lock:
                self.agent.write_waiting.add(header.path)
            gate.wait()
            with self.agent.lock:
                self.agent.write_waiting.discard(header.path)
        with self.agent.lock:
            self.agent.write_chunk_sizes.append(sizes)
            self.agent.write_paths.append(header.path)
            sandbox_id = self._ready(context)
            failure = self.agent.write_failures.get(
                header.path
            ) or self.agent.write_failures.get(ANY_PATH)
            if failure is not None and failure.count != 0:
                if failure.count is not None:
                    failure.count -= 1
                if isinstance(failure.reason, grpc.StatusCode):
                    context.abort(failure.reason, "injected write failure")
                else:
                    abort_daemon(context, failure.reason, "injected write failure")
            key = self._parents_followed(
                context,
                self._file_key(context, sandbox_id, header.session_id, header.path),
            )
            path = key[2]
            if key in self.agent.files and not header.overwrite:
                abort_daemon(context, SandboxDaemonErrorReason.FILE_EXISTS, path)
            # Like the daemon: a file cannot be a parent, or replace a folder.
            for k in self.agent.files:
                if k[:2] == key[:2] and (
                    path.startswith(f"{k[2]}/") or k[2].startswith(f"{path}/")
                ):
                    abort_daemon(
                        context, SandboxDaemonErrorReason.INVALID_ARGUMENT, path
                    )
            digest = self._store(
                context, sandbox_id, header.session_id, path, data, header
            )
            return sandboxd_pb2.WriteFileResponse(
                info=self._info(path, len(data), mode=self.agent.file_modes[key]),
                sha256=digest,
            )

    def UploadFile(  # noqa: N802
        self,
        request_iterator: Iterator[sandboxd_pb2.UploadFileRequest],
        context: grpc.ServicerContext,
    ) -> sandboxd_pb2.UploadFileResponse:
        first = next(request_iterator)
        if first.WhichOneof("part") != "header":
            abort_daemon(
                context, SandboxDaemonErrorReason.INVALID_ARGUMENT, "header first"
            )
        header = first.header
        data = b"".join(r.data for r in request_iterator)
        with self.agent.lock:
            sandbox_id = self._ready(context)
            if "/" in header.file_name or not header.file_name:
                abort_daemon(
                    context, SandboxDaemonErrorReason.INVALID_ARGUMENT, "bad name"
                )
            directory = self._check_path(context, header.directory or "attachments")
            stem, dot, ext = header.file_name.partition(".")
            path = f"{directory}/{header.file_name}"
            n = 0
            while (sandbox_id, header.session_id, path) in self.agent.files:
                n += 1
                path = f"{directory}/{stem}_{n}{dot}{ext}"
            digest = self._store(
                context, sandbox_id, header.session_id, path, data, header
            )
            return sandboxd_pb2.UploadFileResponse(
                info=self._info(path, len(data)), sha256=digest
            )

    def ListFiles(  # noqa: N802
        self, request: sandboxd_pb2.ListFilesRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.ListFilesResponse:
        with self.agent.lock:
            sandbox_id = self._ready(context)
            # With no session ID, an absolute path, as for the other calls.
            base = (
                self._check_path(context, request.path)
                if request.session_id
                else self._file_key(context, sandbox_id, "", request.path)[2]
            )
            files: dict[str, bytes | None] = {
                **self._session_files(sandbox_id, request.session_id),
                # Links, which have no data.
                **{
                    path: None
                    for (sid, session, path) in self.agent.links
                    if sid == sandbox_id and session == request.session_id
                },
            }
            self.agent.list_requests.append((base, request.recursive))
            # The directory that the path names through its links; entries
            # keep the requested path.
            real = (
                self._followed(
                    context,
                    self._parents_followed(
                        context, (sandbox_id, request.session_id, base)
                    ),
                )[2]
                if request.session_id and base
                else base
            )
        prefix = f"{base}/" if base else ""
        real_prefix = f"{real}/" if real else ""
        under = {
            prefix + p[len(real_prefix) :]: d
            for p, d in files.items()
            if p.startswith(real_prefix)
        }
        if base and not under:
            abort_daemon(context, SandboxDaemonErrorReason.FILE_NOT_FOUND, base)
        exclude = set(request.exclude_names)
        # Entries at depth <= max_depth (1 = the directory itself).
        max_depth = (request.max_depth or 64) if request.recursive else 1
        depth_cut = False
        dirs: set[str] = set()
        entries: list[sandboxd_pb2.FileInfo] = []
        for path, data in sorted(under.items(), key=lambda item: item[0]):
            rel = path[len(prefix) :]
            if _skipped(rel, exclude, skip_hidden=request.skip_hidden):
                continue
            parts = rel.split("/")
            for i in range(1, min(len(parts), max_depth + 1)):
                dirs.add(prefix + "/".join(parts[:i]))
            if len(parts) > max_depth:
                depth_cut = depth_cut or request.recursive
                continue
            entries.append(
                sandboxd_pb2.FileInfo(
                    path=path,
                    name=path.rsplit("/", 1)[-1],
                    type=sandboxd_pb2.FILE_TYPE_SYMLINK,
                    mode=0o777,
                )
                if data is None
                else self._info(
                    path,
                    len(data),
                    modified_at=self.agent.file_times.get(
                        (sandbox_id, request.session_id, path)
                    ),
                )
            )
        listing = [self._info(d, 0, directory=True) for d in sorted(dirs)] + entries
        limit = request.max_entries or self.agent.list_max_entries or 10_000
        response_limit = self.agent.list_response_limit
        if response_limit is not None and min(len(listing), limit) > response_limit:
            context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED, "the response is over the limit"
            )
        return sandboxd_pb2.ListFilesResponse(
            entries=listing[:limit], truncated=len(listing) > limit or depth_cut
        )

    def RenameFile(  # noqa: N802
        self, request: sandboxd_pb2.RenameFileRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.RenameFileResponse:
        with self.agent.lock:
            sandbox_id = self._ready(context)
            self.agent.daemon_calls.append(("RenameFile", request.path))
            src = self._file_key(context, sandbox_id, "", request.path)
            dst = self._file_key(context, sandbox_id, "", request.to)
            if (
                request.session_id
                or src[2].rsplit("/", 1)[0] != dst[2].rsplit("/", 1)[0]
            ):
                abort_daemon(
                    context, SandboxDaemonErrorReason.INVALID_ARGUMENT, request.to
                )
            stores: list[dict[tuple[str, str, str], Any]] = [
                self.agent.files,
                self.agent.links,
                self.agent.file_modes,
            ]

            def under(key: tuple[str, str, str]) -> list[tuple[str, str, str]]:
                return [
                    k
                    for store in stores
                    for k in store
                    if k[:2] == key[:2]
                    and (k[2] == key[2] or k[2].startswith(f"{key[2]}/"))
                ]

            if not under(src) or (request.exchange and not under(dst)):
                abort_daemon(context, SandboxDaemonErrorReason.FILE_NOT_FOUND, src[2])
            if not request.exchange and under(dst):
                abort_daemon(context, SandboxDaemonErrorReason.FILE_EXISTS, dst[2])
            for store in stores:
                moved = {
                    k: v
                    for k, v in store.items()
                    if k[:2] == src[:2]
                    and (k[2] == src[2] or k[2].startswith(f"{src[2]}/"))
                }
                swapped = {
                    k: v
                    for k, v in store.items()
                    if k[:2] == dst[:2]
                    and (k[2] == dst[2] or k[2].startswith(f"{dst[2]}/"))
                }
                for k in [*moved, *swapped]:
                    del store[k]
                for k, v in moved.items():
                    store[(*k[:2], dst[2] + k[2][len(src[2]) :])] = v
                for k, v in swapped.items():
                    store[(*k[:2], src[2] + k[2][len(dst[2]) :])] = v
            if self.agent.lose_rename_reply:
                self.agent.lose_rename_reply = False
                context.abort(grpc.StatusCode.UNAVAILABLE, "connection reset")
            return sandboxd_pb2.RenameFileResponse()

    def DeleteFile(  # noqa: N802
        self, request: sandboxd_pb2.DeleteFileRequest, context: grpc.ServicerContext
    ) -> sandboxd_pb2.DeleteFileResponse:
        with self.agent.lock:
            sandbox_id = self._ready(context)
            self.agent.daemon_calls.append(("DeleteFile", request.path))
            if not request.session_id and request.path.startswith(WORKSPACES + "/"):
                # VM-wide delete of a whole session directory.
                session = request.path.removeprefix(WORKSPACES + "/")
                gone = [k for k in self.agent.files if k[:2] == (sandbox_id, session)]
                for k in gone:
                    del self.agent.files[k]
                return sandboxd_pb2.DeleteFileResponse(deleted=bool(gone))
            key = self._parents_followed(
                context,
                self._file_key(context, sandbox_id, request.session_id, request.path),
            )
            path = key[2]
            # Like the daemon: a path under a file is not a path.
            if any(
                k[:2] == key[:2] and path.startswith(f"{k[2]}/")
                for k in self.agent.files
            ):
                abort_daemon(context, SandboxDaemonErrorReason.INVALID_ARGUMENT, path)
            self.agent.file_modes.pop(key, None)
            if (
                self.agent.files.pop(key, None) is not None
                or self.agent.links.pop(key, None) is not None
            ):
                return sandboxd_pb2.DeleteFileResponse(deleted=True)
            below = [
                k
                for k in self.agent.files
                if k[:2] == key[:2] and k[2].startswith(f"{path}/")
            ]
            if below and not request.recursive:
                abort_daemon(
                    context, SandboxDaemonErrorReason.INVALID_ARGUMENT, "a directory"
                )
            for k in below:
                del self.agent.files[k]
            return sandboxd_pb2.DeleteFileResponse(deleted=bool(below))

    def ZipFiles(  # noqa: N802
        self, request: sandboxd_pb2.ZipFilesRequest, context: grpc.ServicerContext
    ) -> Iterator[sandboxd_pb2.ZipFilesResponse]:
        with self.agent.lock:
            sandbox_id = self._ready(context)
            base = self._check_path(context, request.path)
            files = self._session_files(sandbox_id, request.session_id)
            limit = self.agent.zip_max_input_bytes
        prefix = f"{base}/" if base else ""
        if base and not any(p.startswith(prefix) for p in files):
            abort_daemon(context, SandboxDaemonErrorReason.FILE_NOT_FOUND, base)
        exclude = set(request.exclude_names)
        members = {
            p[len(prefix) :]: d
            for p, d in files.items()
            if p.startswith(prefix)
            and not _skipped(p[len(prefix) :], exclude, skip_hidden=request.skip_hidden)
        }
        archive = _zip(members)
        half = len(archive) // 2
        yield sandboxd_pb2.ZipFilesResponse(data=archive[:half])
        input_bytes = sum(len(d) for d in members.values())
        if limit is not None and input_bytes > limit:
            abort_daemon(context, SandboxDaemonErrorReason.LIMIT_EXCEEDED, "too big")
        yield sandboxd_pb2.ZipFilesResponse(data=archive[half:])
        yield sandboxd_pb2.ZipFilesResponse(
            summary=sandboxd_pb2.ZipSummary(
                files=len(members), input_bytes=input_bytes, zip_bytes=len(archive)
            )
        )


class RunningFakeAgent:
    def __init__(
        self,
        agent: FakeHostAgent,
        server_credentials: grpc.ServerCredentials | None = None,
    ) -> None:
        self.agent = agent
        # Room for the pod's parallel copies and the calls beside them.
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=32))
        hostagent_pb2_grpc.add_HostAgentServicer_to_server(agent, self.server)
        sandboxd_pb2_grpc.add_SandboxdServicer_to_server(
            FakeSandboxd(agent), self.server
        )
        if server_credentials is None:
            port = self.server.add_insecure_port("127.0.0.1:0")
        else:
            port = self.server.add_secure_port("127.0.0.1:0", server_credentials)
        self.address = f"127.0.0.1:{port}"
        self.server.start()

    def stop(self) -> None:
        self.server.stop(grace=None)


class _KeepOpenClient(HostAgentClient):
    def close(self) -> None:
        return None


class InsecureClientFactory(HostAgentClientFactory):
    """Plain-text channels for the fake agents, one per address."""

    def __init__(self) -> None:
        self._channels: dict[str, grpc.Channel] = {}

    def client(self, address: str) -> HostAgentClient:
        channel = self._channels.get(address)
        if channel is None:
            channel = grpc.insecure_channel(
                address,
                [
                    ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
                    ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
                ],
            )
            self._channels[address] = channel
        return _KeepOpenClient(channel)

    def close(self) -> None:
        for channel in self._channels.values():
            channel.close()
