"""The backend of each harness sandbox when Firecracker and the container
backend are both on (`SANDBOX_RUNTIME=auto` on Kubernetes with
`SANDBOX_CONTAINER_HARNESS=true`).

A sandbox stays on its backend while it runs there: a container record
keeps it on the container backend, and a Firecracker placement keeps it on
Firecracker while a live node serves the template. A sandbox that runs on
neither starts on Firecracker when a live node serves the template, else on
the container backend. A short choice mark makes concurrent first calls
agree. Errors of the chosen backend, such as a Firecracker capacity error,
reach the caller: there is no fallback to the other backend. Sessions come
back from their saves on either backend.
"""

from collections.abc import Callable, Generator, Iterable, Sequence
from typing import IO
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.microvm.models import FileListing, HarnessBackend
from onyx.microvm.registry import get_sandbox_placement
from onyx.server.features.build.configs import SANDBOX_HARNESS_START_TIMEOUT_SECONDS
from onyx.server.features.build.sandbox.container.state import get_container_record
from onyx.server.features.build.sandbox.harness_base import (
    HarnessSandbox,
    SessionFiles,
)
from onyx.server.features.build.sandbox.models import (
    ExecEvent,
    FileSet,
    HarnessSandboxKey,
    HarnessSandboxRef,
    RenderedPreview,
    RenderFileBytes,
    RenderSessionFile,
    SandboxPathInfo,
)

_CHOICE_PREFIX = "sandbox_harness:backend:"
# Longer than a start, so the calls of one start agree.
CHOICE_SECONDS = int(SANDBOX_HARNESS_START_TIMEOUT_SECONDS) + 60


def running_backend(tenant_id: str, sandbox_id: UUID) -> HarnessBackend | None:
    """The backend that has a record of the sandbox, without a choice."""
    tenant_cache = get_cache_backend(tenant_id=tenant_id)
    if get_container_record(tenant_cache, sandbox_id) is not None:
        return HarnessBackend.CONTAINER
    if get_sandbox_placement(tenant_cache, sandbox_id) is not None:
        return HarnessBackend.FIRECRACKER
    return None


def choose_backend(
    tenant_id: str, sandbox_id: UUID, *, firecracker_available: Callable[[], bool]
) -> HarnessBackend:
    tenant_cache = get_cache_backend(tenant_id=tenant_id)
    if get_container_record(tenant_cache, sandbox_id) is not None:
        return HarnessBackend.CONTAINER
    live = firecracker_available()
    # Without a live node the placed VM cannot serve: its node is dead.
    if live and get_sandbox_placement(tenant_cache, sandbox_id) is not None:
        return HarnessBackend.FIRECRACKER
    pick = HarnessBackend.FIRECRACKER if live else HarnessBackend.CONTAINER
    key = _CHOICE_PREFIX + str(sandbox_id)
    if tenant_cache.set_if_absent(key, pick.value, ex=CHOICE_SECONDS):
        return pick
    raw = tenant_cache.get(key)
    if raw is None:
        return pick
    try:
        return HarnessBackend(raw.decode())
    except ValueError:
        return pick


class SelectingHarnessSandbox(HarnessSandbox):
    """Sends each call to the backend of its sandbox."""

    def __init__(
        self,
        *,
        firecracker: HarnessSandbox,
        container: HarnessSandbox,
        firecracker_available: Callable[[], bool],
    ) -> None:
        self._backends: dict[HarnessBackend, HarnessSandbox] = {
            HarnessBackend.FIRECRACKER: firecracker,
            HarnessBackend.CONTAINER: container,
        }
        self._firecracker_available = firecracker_available

    def backend_for(self, sandbox: HarnessSandboxKey) -> HarnessSandbox:
        """The backend for a call that can start the sandbox."""
        return self._backends[
            choose_backend(
                sandbox.tenant_id,
                sandbox.sandbox_id,
                firecracker_available=self._firecracker_available,
            )
        ]

    def _running(self, tenant_id: str, sandbox_id: UUID) -> HarnessSandbox:
        """The backend for a call that never starts the sandbox. Without a
        running sandbox either one answers: the activity marks are shared."""
        backend = running_backend(tenant_id, sandbox_id)
        return self._backends[backend or HarnessBackend.CONTAINER]

    # Calls that can start the sandbox

    def ensure_running(self, ref: HarnessSandboxRef) -> None:
        self.backend_for(ref).ensure_running(ref)

    def install_skill(
        self, ref: HarnessSandboxRef, name: str, version: str, files: FileSet
    ) -> bool:
        return self.backend_for(ref).install_skill(ref, name, version, files)

    def exec_command(
        self,
        ref: HarnessSandboxRef,
        cmd: str,
        *,
        workdir: str | None = None,
        yield_time_ms: int | None = None,
    ) -> Generator[ExecEvent]:
        return self.backend_for(ref).exec_command(
            ref, cmd, workdir=workdir, yield_time_ms=yield_time_ms
        )

    def write_stdin(
        self,
        ref: HarnessSandboxRef,
        exec_session_id: str,
        chars: str = "",
        *,
        yield_time_ms: int | None = None,
    ) -> Generator[ExecEvent]:
        return self.backend_for(ref).write_stdin(
            ref, exec_session_id, chars, yield_time_ms=yield_time_ms
        )

    def read_file(self, ref: HarnessSandboxRef, path: str, *, max_bytes: int) -> bytes:
        return self.backend_for(ref).read_file(ref, path, max_bytes=max_bytes)

    def write_file(
        self,
        ref: HarnessSandboxRef,
        path: str,
        data: bytes | IO[bytes] | list[bytes],
        *,
        mode: int = 0o644,
        timeout_seconds: float | None = None,
    ) -> None:
        self.backend_for(ref).write_file(
            ref, path, data, mode=mode, timeout_seconds=timeout_seconds
        )

    def delete_listed_files(
        self,
        ref: HarnessSandboxRef,
        directory: str,
        select: Callable[[FileListing], Iterable[str]],
        *,
        max_entries: int,
    ) -> None:
        self.backend_for(ref).delete_listed_files(
            ref, directory, select, max_entries=max_entries
        )

    def stat_files(
        self, ref: HarnessSandboxRef, paths: Sequence[str]
    ) -> list[SandboxPathInfo]:
        return self.backend_for(ref).stat_files(ref, paths)

    def delete_file(self, ref: HarnessSandboxRef, path: str) -> bool:
        return self.backend_for(ref).delete_file(ref, path)

    def session_files(self, ref: HarnessSandboxRef) -> SessionFiles:
        return self.backend_for(ref).session_files(ref)

    def render_preview(
        self,
        source: RenderSessionFile | RenderFileBytes,
        *,
        first_page: bool,
        budget_seconds: float,
    ) -> RenderedPreview | None:
        sandbox: HarnessSandboxKey = (
            source.ref if isinstance(source, RenderSessionFile) else source.sandbox
        )
        return self.backend_for(sandbox).render_preview(
            source, first_page=first_page, budget_seconds=budget_seconds
        )

    # Activity: never starts the sandbox

    def touch(self, ref: HarnessSandboxRef) -> None:
        self._running(ref.tenant_id, ref.sandbox_id).touch(ref)

    def begin_turn(self, ref: HarnessSandboxRef) -> None:
        self._running(ref.tenant_id, ref.sandbox_id).begin_turn(ref)

    def end_turn(self, ref: HarnessSandboxRef) -> None:
        self._running(ref.tenant_id, ref.sandbox_id).end_turn(ref)

    def set_approval_parked(self, ref: HarnessSandboxRef, parked: bool) -> None:
        self._running(ref.tenant_id, ref.sandbox_id).set_approval_parked(ref, parked)

    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:
        return self._running(tenant_id, sandbox_id).is_busy(
            tenant_id=tenant_id, sandbox_id=sandbox_id
        )

    # Purge: on both backends, since the sandbox may have run on either.

    def purge_session(
        self,
        *,
        tenant_id: str,
        sandbox_id: UUID,
        session_id: UUID,
        retention: bool = False,
    ) -> None:
        errors: list[Exception] = []
        for backend in self._backends.values():
            try:
                backend.purge_session(
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    session_id=session_id,
                    retention=retention,
                )
            except Exception as e:
                errors.append(e)
        if errors:
            raise errors[0]

    def purge_sandbox(
        self,
        *,
        tenant_id: str,
        sandbox_id: UUID,
        session_ids: list[UUID] | None = None,
    ) -> None:
        errors: list[Exception] = []
        for backend in self._backends.values():
            try:
                backend.purge_sandbox(
                    tenant_id=tenant_id, sandbox_id=sandbox_id, session_ids=session_ids
                )
            except Exception as e:
                errors.append(e)
        if errors:
            raise errors[0]
