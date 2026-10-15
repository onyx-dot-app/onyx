"""Concrete Firecracker-backed Craft sandbox manager."""

from __future__ import annotations

import base64
import gzip
import io
import json
import shlex
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable, Generator, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO, NoReturn
from uuid import UUID

from pydantic import BaseModel

from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import (
    OPENCODE_SERVE_PORT,
    TURN_BUDGET_FILE_NAME,
)
from onyx.server.features.build.sandbox.event_schema import SandboxEvent
from onyx.server.features.build.sandbox.image.guest import PROTOCOL_VERSION
from onyx.server.features.build.sandbox.image.guest.models import (
    MAX_HISTORY_ARCHIVE_BYTES,
    FilesystemEntry,
    OutputsManifestResponse,
)
from onyx.server.features.build.sandbox.models import (
    CraftLLMProviderConfig,
    CraftMCPServerConfig,
    FatalWriteError,
    FileSet,
    PromptAttachment,
    PushFailure,
    PushResult,
    RetriableWriteError,
    SandboxExecError,
    SandboxInfo,
    SnapshotResult,
)
from onyx.server.features.build.sandbox.nextjs_dev import (
    WEBAPP_ABSENT_SENTINEL,
    WEBAPP_AUTOSTART_SENTINEL,
    build_webapp_restore_script,
)
from onyx.server.features.build.sandbox.runtime import (
    SandboxRuntime,
    get_sandbox_runtime,
)
from onyx.server.features.build.sandbox.serve_transport import (
    ServeConnectionInfo,
    _ServeMixin,
)
from onyx.server.features.build.sandbox.session_workspace import (
    SESSION_CONFIG_COMPLETE_SENTINEL,
    SESSIONS_ROOT,
    WORKSPACE_SETUP_COMPLETE_SENTINEL,
    build_opencode_dependency_setup_command,
    build_session_workspace_setup_script,
)
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.util.agent_instructions import (
    ATTACHMENTS_SECTION_CONTENT,
    generate_agent_instructions,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_provider_opencode_config,
)
from onyx.server.features.build.timeouts import (
    BULK_TRANSFER_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS,
    PROVISION_DEADLINE_SECONDS,
    RPC_TIMEOUT_SECONDS,
    TURN_FINAL_NOTICE_MARGIN_SECONDS,
    WORKSPACE_SETUP_DEADLINE_SECONDS,
)
from onyx.server.features.build.utils import get_opencode_disabled_tools
from onyx.server.settings.store import load_settings
from onyx.skills.built_in import BUILTIN_SKILLS_PATH
from onyx.utils.logger import setup_logger

logger = setup_logger()

_MAX_BUNDLE_BYTES = 100 * 1024 * 1024
_SNAPSHOT_SLOTS = threading.BoundedSemaphore(4)


_DOCUMENT_PREVIEW_FILES: FileSet = {
    "preview.py": (BUILTIN_SKILLS_PATH / "pptx/scripts/preview.py").read_bytes(),
    "office/soffice.py": (
        BUILTIN_SKILLS_PATH / "pptx/scripts/office/soffice.py"
    ).read_bytes(),
}
_DOCUMENT_PREVIEW_VERSION: str = sha256(
    b"".join(
        name.encode() + b"\0" + sha256(content).digest()
        for name, content in sorted(_DOCUMENT_PREVIEW_FILES.items())
    )
).hexdigest()
_DOCUMENT_PREVIEW_MOUNT: str = (
    f"/workspace/managed/document-preview/{_DOCUMENT_PREVIEW_VERSION}"
)


def document_preview_command(
    document_path: str,
    cache_dir: str,
    session_root: str,
    *,
    script_path: str = f"{_DOCUMENT_PREVIEW_MOUNT}/preview.py",
    first_page_only: bool = False,
) -> list[str]:
    """Run the packaged converter without replacing the agent's managed skills."""
    return [
        "python",
        script_path,
        document_path,
        cache_dir,
        *(["--first-page"] if first_page_only else []),
        "--session-root",
        session_root,
    ]


def parse_document_preview_response(
    output: str, session_root: str
) -> tuple[list[str], bool]:
    """Validate the converter protocol and return session-relative page paths."""
    lines: list[str] = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Empty response from document conversion")
    errors: dict[str, str] = {
        "ERROR_NOT_FOUND": "Document not found",
        "ERROR_ACCESS_DENIED": "Access denied: source escapes session workspace",
        "ERROR_TOO_LARGE": "Document exceeds thumbnail size limit",
        "ERROR_TIMEOUT": "Document thumbnail conversion timed out",
        "ERROR_SOURCE_CHANGED": "Document changed while rendering; retry preview",
        "ERROR_NO_PDF": "soffice did not produce a PDF file",
        "ERROR_CONVERSION": "Document conversion failed",
    }
    if lines[0] in errors:
        raise ValueError(errors[lines[0]])
    if lines[0] not in {"CACHED", "GENERATED"}:
        raise ValueError("Invalid document conversion status")
    if len(lines) == 1:
        raise ValueError("Document conversion produced no pages")
    root: PurePosixPath = PurePosixPath(session_root)
    paths: list[str] = []
    for value in lines[1:]:
        path: PurePosixPath = PurePosixPath(value)
        if ".." in path.parts or not path.is_relative_to(root):
            raise ValueError("Access denied: preview escapes session workspace")
        if (
            not path.name.startswith("slide-")
            or path.suffix != ".jpg"
            or not path.stem[6:].isdigit()
        ):
            raise ValueError("Invalid document preview page path")
        paths.append(str(path.relative_to(root)))
    return paths, lines[0] == "CACHED"


class _UploadResponse(BaseModel):
    path: str


class _DeleteResponse(BaseModel):
    deleted: bool


class _StatusResponse(BaseModel):
    protocol: int
    ready: bool
    history_restored: bool


class _WorkspaceExistsResponse(BaseModel):
    exists: bool


class _WorkspaceListResponse(BaseModel):
    session_ids: list[UUID]


class _UploadStatsResponse(BaseModel):
    file_count: int
    total_size_bytes: int


def _build_targz(files: FileSet) -> bytes:
    total = sum(len(content) for content in files.values())
    if total > _MAX_BUNDLE_BYTES:
        raise FatalWriteError(
            f"Bundle size {total} exceeds {_MAX_BUNDLE_BYTES} byte limit"
        )
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for name in sorted(files):
                content = files[name]
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise FatalWriteError(f"Invalid managed file path: {name}")
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class SandboxManager(_ServeMixin):
    def __init__(self) -> None:
        self._runtime: SandboxRuntime = get_sandbox_runtime()
        self._snapshot_manager = SnapshotManager(get_default_file_store())
        self._init_serve_state()
        build_dir = Path(__file__).parent.parent
        self._agent_instructions_template_path = build_dir / "AGENTS.template.md"

    def _guest(
        self,
        sandbox_id: UUID,
        operation: str,
        metadata: dict[str, object] | None = None,
        *,
        stdin: bytes | BinaryIO | None = None,
        timeout: float = RPC_TIMEOUT_SECONDS,
    ) -> bytes:
        try:
            result = self._runtime.helper(
                sandbox_id,
                operation,
                metadata or {},
                stdin=stdin,
                timeout=timeout,
            )
        except SandboxExecError as error:
            self._raise_guest_error(operation, error)
        return result.stdout

    @staticmethod
    def _raise_guest_error(operation: str, error: SandboxExecError) -> NoReturn:
        detail = f"{operation}: {error}; {error.stderr}".rstrip("; ")
        if (
            operation
            in {
                "list-directory",
                "read-file",
                "upload-file",
                "delete-file",
                "write-file",
            }
            and error.returncode == 1
            and error.stderr.startswith(
                ("ValueError:", "FileNotFoundError:", "FilesystemPathError:")
            )
        ):
            raise ValueError(detail) from error
        raise SandboxExecError(
            detail, returncode=error.returncode, stderr=error.stderr
        ) from error

    def _guest_stream(
        self,
        sandbox_id: UUID,
        operation: str,
        metadata: dict[str, object] | None = None,
        *,
        stdin: bytes | BinaryIO | None = None,
        timeout: float = BULK_TRANSFER_TIMEOUT_SECONDS,
    ) -> Generator[bytes, None, None]:
        try:
            yield from self._runtime.helper_stream(
                sandbox_id,
                operation,
                metadata or {},
                stdin=stdin,
                timeout=timeout,
            )
        except SandboxExecError as error:
            self._raise_guest_error(operation, error)

    def _guest_json[T: BaseModel](
        self,
        sandbox_id: UUID,
        operation: str,
        response_type: type[T],
        metadata: dict[str, object] | None = None,
        *,
        stdin: bytes | BinaryIO | None = None,
        timeout: float = RPC_TIMEOUT_SECONDS,
    ) -> T:
        raw = self._guest(
            sandbox_id,
            operation,
            metadata,
            stdin=stdin,
            timeout=timeout,
        )
        try:
            return response_type.model_validate_json(raw)
        except ValueError as error:
            raise RuntimeError(
                f"Invalid guest response for {operation}: {raw[-500:]!r}"
            ) from error

    def _run(
        self,
        sandbox_id: UUID,
        argv: Sequence[str],
        *,
        stdin: bytes | BinaryIO | None = None,
        timeout: float = RPC_TIMEOUT_SECONDS,
        cwd: str = "/workspace",
    ) -> str:
        return self._guest(
            sandbox_id,
            "run",
            {
                "argv": list(argv),
                "cwd": cwd,
                "timeout_seconds": max(0.1, timeout - 2),
                "has_stdin": stdin is not None,
            },
            stdin=stdin,
            timeout=timeout,
        ).decode("utf-8", errors="replace")

    def _run_script(
        self,
        sandbox_id: UUID,
        script: str,
        *,
        timeout: float = WORKSPACE_SETUP_DEADLINE_SECONDS,
    ) -> str:
        return self._run(
            sandbox_id, ["/bin/bash", "-s"], stdin=script.encode(), timeout=timeout
        )

    def _load_agent_instructions(
        self,
        connectable_apps_section: str,
        provider: str | None = None,
        model_name: str | None = None,
        disabled_tools: list[str] | None = None,
        user_name: str | None = None,
    ) -> str:
        return generate_agent_instructions(
            template_path=self._agent_instructions_template_path,
            connectable_apps_section=connectable_apps_section,
            provider=provider,
            model_name=model_name,
            disabled_tools=disabled_tools,
            user_name=user_name,
            organization_instructions=load_settings().craft_instructions,
        )

    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        onyx_pat: str | None,
        provisioning_attempt_number: int,
    ) -> SandboxInfo:
        deadline = time.monotonic() + PROVISION_DEADLINE_SECONDS

        def initialize(sandbox_id: UUID, timeout: float) -> None:
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Firecracker guest bootstrap timed out")
                try:
                    status = self._guest_json(
                        sandbox_id,
                        "status",
                        _StatusResponse,
                        timeout=min(remaining, RPC_TIMEOUT_SECONDS),
                    )
                except SandboxExecError as error:
                    if error.returncode is not None:
                        raise
                    logger.warning(
                        "Guest bootstrap query is not ready for %s: %s",
                        sandbox_id,
                        error,
                    )
                    time.sleep(
                        min(POLL_INTERVAL_SECONDS, max(0, deadline - time.monotonic()))
                    )
                    continue
                if status.protocol != PROTOCOL_VERSION:
                    raise RuntimeError("Unsupported Craft guest protocol")
                if status.ready:
                    if not status.history_restored:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("Firecracker history restore timed out")
                        self.restore_opencode_history_snapshot(
                            sandbox_id,
                            tenant_id,
                            timeout_seconds=remaining,
                        )
                    return
                time.sleep(
                    min(POLL_INTERVAL_SECONDS, max(0, deadline - time.monotonic()))
                )

        info = self._runtime.provision(
            sandbox_id,
            user_id,
            tenant_id,
            onyx_pat,
            provisioning_attempt_number,
            initialize,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._wait_for_opencode_serve_ready(
            sandbox_id, timeout=remaining
        ):
            raise TimeoutError("Authenticated OpenCode startup timed out")
        return info

    def terminate(self, sandbox_id: UUID) -> None:
        self._close_all_sandbox_buses(sandbox_id)
        self._runtime.terminate(sandbox_id)

    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: CraftLLMProviderConfig,
        nextjs_port: int | None,
        connectable_apps_section: str,
        user_name: str | None = None,
        mcp_servers: Sequence[CraftMCPServerConfig] = (),
    ) -> None:
        disabled_tools = get_opencode_disabled_tools()
        session_path = f"{SESSIONS_ROOT}/{session_id}"
        setup_script = build_session_workspace_setup_script(
            session_path=session_path,
            agents_md=self._load_agent_instructions(
                connectable_apps_section=connectable_apps_section,
                provider=llm_config.provider,
                model_name=llm_config.model_name,
                disabled_tools=disabled_tools,
                user_name=user_name,
            ),
            session_opencode_config_json=json.dumps(
                build_provider_opencode_config(
                    llm_config,
                    disabled_tools=disabled_tools,
                    mcp_servers=mcp_servers,
                    session_id=str(session_id),
                )
            ),
            nextjs_port=nextjs_port,
        )
        response = self._run_script(sandbox_id, setup_script)
        if WORKSPACE_SETUP_COMPLETE_SENTINEL not in response.splitlines():
            raise RuntimeError(
                f"Session workspace setup for {session_id} did not complete "
                f"(output tail: {response[-500:]!r})"
            )

    def cleanup_session_workspace(self, sandbox_id: UUID, session_id: UUID) -> None:
        self._close_session_buses(sandbox_id, session_id)
        if not self._runtime.exists(sandbox_id):
            return
        self._guest_json(
            sandbox_id,
            "cleanup-workspace",
            _StatusOk,
            {"session_id": str(session_id)},
            timeout=WORKSPACE_SETUP_DEADLINE_SECONDS,
        )

    def regenerate_session_config(
        self,
        *,
        sandbox_id: UUID,
        session_id: UUID,
        agent_provider: str | None,
        agent_model: str | None,
        connectable_apps_section: str,
        user_name: str | None = None,
        llm_config: CraftLLMProviderConfig | None = None,
        mcp_servers: Sequence[CraftMCPServerConfig] = (),
    ) -> None:
        disabled_tools = get_opencode_disabled_tools()
        session_path = shlex.quote(f"/workspace/sessions/{session_id}")
        agent_instructions = self._load_agent_instructions(
            connectable_apps_section=connectable_apps_section,
            provider=agent_provider,
            model_name=agent_model,
            disabled_tools=disabled_tools,
            user_name=user_name,
        )
        session_opencode_config = (
            json.dumps(
                build_provider_opencode_config(
                    llm_config,
                    disabled_tools=disabled_tools,
                    mcp_servers=mcp_servers,
                    session_id=str(session_id),
                )
            )
            if llm_config is not None
            else None
        )
        session_opencode_config_setup = (
            f"printf '%s' {shlex.quote(session_opencode_config)} > "
            f"{session_path}/opencode.json"
            if session_opencode_config is not None
            else ""
        )
        attachments_content_b64 = base64.b64encode(
            ATTACHMENTS_SECTION_CONTENT.encode()
        ).decode()
        config_script = f"""
set -e
mkdir -p {session_path}/.opencode
{build_opencode_dependency_setup_command(session_path)}
ln -sfn /workspace/managed/skills {session_path}/.opencode/skills
ln -sfn /workspace/managed/user_library {session_path}/user_library
printf '%s' {shlex.quote(agent_instructions)} > {session_path}/AGENTS.md
{session_opencode_config_setup}
if [ -n "$(find {session_path}/attachments -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
    printf '\\n\\n' >> {session_path}/AGENTS.md
    echo '{attachments_content_b64}' | base64 -d >> {session_path}/AGENTS.md
fi
echo "{SESSION_CONFIG_COMPLETE_SENTINEL}"
"""
        response = self._run_script(sandbox_id, config_script)
        if SESSION_CONFIG_COMPLETE_SENTINEL not in response.splitlines():
            raise RuntimeError(
                f"Session config regeneration for {session_id} did not complete "
                f"(output tail: {response[-500:]!r})"
            )

    @contextmanager
    def _snapshot_archive(
        self,
        sandbox_id: UUID,
        operation: str,
        metadata: dict[str, object],
        timeout: float,
    ) -> Iterator[BinaryIO]:
        deadline = time.monotonic() + timeout
        size_limit = (
            MAX_HISTORY_ARCHIVE_BYTES
            if operation == "snapshot-history"
            else _MAX_BUNDLE_BYTES
        )
        if not _SNAPSHOT_SLOTS.acquire(timeout=timeout):
            raise TimeoutError("Craft snapshot capacity exhausted")
        try:
            with tempfile.TemporaryFile(mode="w+b") as archive:
                size = 0
                with closing(
                    self._guest_stream(
                        sandbox_id,
                        operation,
                        metadata,
                        timeout=max(0.1, deadline - time.monotonic()),
                    )
                ) as chunks:
                    for chunk in chunks:
                        size += len(chunk)
                        if size > size_limit:
                            raise ValueError(
                                f"Craft {operation} archive exceeds {size_limit} byte limit"
                            )
                        archive.write(chunk)
                archive.seek(0)
                yield archive
        finally:
            _SNAPSHOT_SLOTS.release()

    def create_snapshot(
        self, sandbox_id: UUID, session_id: UUID, tenant_id: str
    ) -> SnapshotResult | None:
        with self._snapshot_archive(
            sandbox_id,
            "create-snapshot",
            {"session_id": str(session_id)},
            BULK_TRANSFER_TIMEOUT_SECONDS,
        ) as archive:
            if not archive.read(1):
                return None
            archive.seek(0)
            _, storage_path, size_bytes = (
                self._snapshot_manager.persist_snapshot_from_stream(
                    archive, str(sandbox_id), tenant_id
                )
            )
        return SnapshotResult(storage_path=storage_path, size_bytes=size_bytes)

    def create_opencode_history_snapshot(
        self,
        sandbox_id: UUID,
        tenant_id: str,
        timeout_seconds: float = BULK_TRANSFER_TIMEOUT_SECONDS,
    ) -> bool:
        status = self._guest_json(
            sandbox_id,
            "status",
            _StatusResponse,
            timeout=min(timeout_seconds, RPC_TIMEOUT_SECONDS),
        )
        if not status.ready or not status.history_restored:
            return False
        with self._snapshot_archive(
            sandbox_id, "snapshot-history", {}, timeout_seconds
        ) as archive:
            if not archive.read(1):
                return False
            archive.seek(0)
            self._snapshot_manager.persist_opencode_snapshot_from_stream(
                archive, str(sandbox_id), tenant_id
            )
        return True

    def restore_opencode_history_snapshot(
        self,
        sandbox_id: UUID,
        tenant_id: str,
        timeout_seconds: float = BULK_TRANSFER_TIMEOUT_SECONDS,
    ) -> None:
        if not self._snapshot_manager.has_opencode_history_snapshot(
            tenant_id, str(sandbox_id)
        ):
            self._guest_json(
                sandbox_id,
                "release-history",
                _StatusOk,
                {},
                timeout=timeout_seconds,
            )
            return
        storage_path = self._snapshot_manager.opencode_history_storage_path(
            tenant_id, str(sandbox_id)
        )
        with tempfile.TemporaryFile(mode="w+b") as tmp_file:
            self._snapshot_manager.restore_snapshot_to_stream(
                storage_path, tmp_file, max_bytes=MAX_HISTORY_ARCHIVE_BYTES
            )
            tmp_file.flush()
            tmp_file.seek(0)
            self._guest_json(
                sandbox_id,
                "restore-history",
                _StatusOk,
                {},
                stdin=tmp_file,
                timeout=timeout_seconds,
            )

    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        nextjs_port: int | None,
        llm_config: CraftLLMProviderConfig,
        connectable_apps_section: str,
        mcp_servers: Sequence[CraftMCPServerConfig] = (),
    ) -> None:
        with tempfile.TemporaryFile(mode="w+b") as tmp_file:
            self._snapshot_manager.restore_snapshot_to_stream(
                snapshot_storage_path, tmp_file, max_bytes=_MAX_BUNDLE_BYTES
            )
            tmp_file.flush()
            tmp_file.seek(0)
            self._guest_json(
                sandbox_id,
                "restore-snapshot",
                _StatusOk,
                {"session_id": str(session_id)},
                stdin=tmp_file,
                timeout=BULK_TRANSFER_TIMEOUT_SECONDS,
            )
        self.regenerate_session_config(
            sandbox_id=sandbox_id,
            session_id=session_id,
            agent_provider=llm_config.provider,
            agent_model=llm_config.model_name,
            connectable_apps_section=connectable_apps_section,
            llm_config=llm_config,
            mcp_servers=mcp_servers,
        )
        if nextjs_port is not None:
            session_path = f"/workspace/sessions/{session_id}"
            response = self._run_script(
                sandbox_id,
                build_webapp_restore_script(shlex.quote(session_path), nextjs_port),
            )
            if (
                WEBAPP_AUTOSTART_SENTINEL not in response
                and WEBAPP_ABSENT_SENTINEL not in response
            ):
                raise RuntimeError(
                    f"Webapp restore for session {session_id} did not complete "
                    f"(output tail: {response[-500:]!r})"
                )

    def session_workspace_exists(self, sandbox_id: UUID, session_id: UUID) -> bool:
        response = self._guest_json(
            sandbox_id,
            "workspace-exists",
            _WorkspaceExistsResponse,
            {"session_id": str(session_id)},
        )
        return response.exists

    def list_session_workspaces(self, sandbox_id: UUID) -> list[UUID]:
        response = self._guest_json(
            sandbox_id,
            "list-workspaces",
            _WorkspaceListResponse,
            {},
        )
        return response.session_ids

    def health_check(self, sandbox_id: UUID, timeout: float) -> bool:
        if not self._runtime.health_check(sandbox_id):
            return False
        return self._wait_for_opencode_serve_ready(sandbox_id, timeout=timeout)

    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        response = self._guest_json(
            sandbox_id,
            "list-directory",
            _DirectoryListingResponse,
            {"session_id": str(session_id), "path": path},
        )
        return response.entries

    def get_outputs_manifest(
        self, sandbox_id: UUID, session_id: UUID
    ) -> OutputsManifestResponse:
        response = self._guest_json(
            sandbox_id,
            "outputs-manifest",
            OutputsManifestResponse,
            {"session_id": str(session_id)},
        )
        return response

    def read_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bytes:
        chunks = self._guest_stream(
            sandbox_id,
            "read-file",
            {"session_id": str(session_id), "path": path},
            timeout=BULK_TRANSFER_TIMEOUT_SECONDS,
        )
        with closing(chunks), io.BytesIO() as content:
            size = 0
            for chunk in chunks:
                size += len(chunk)
                if size > _MAX_BUNDLE_BYTES:
                    raise ValueError("Sandbox file exceeds 100 MiB download limit")
                content.write(chunk)
            return content.getvalue()

    def upload_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        response = self._guest_json(
            sandbox_id,
            "upload-file",
            _UploadResponse,
            {"session_id": str(session_id), "filename": filename},
            stdin=content,
            timeout=BULK_TRANSFER_TIMEOUT_SECONDS,
        )
        self._ensure_agents_md_attachments_section(sandbox_id, session_id)
        return response.path

    def delete_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bool:
        response = self._guest_json(
            sandbox_id,
            "delete-file",
            _DeleteResponse,
            {"session_id": str(session_id), "path": path},
        )
        return response.deleted

    def write_sandbox_file(
        self,
        sandbox_id: UUID,
        path: str,
        content: str,
    ) -> None:
        self._guest_json(
            sandbox_id,
            "write-file",
            _StatusOk,
            {"path": path},
            stdin=content.encode(),
            timeout=BULK_TRANSFER_TIMEOUT_SECONDS,
        )

    def get_upload_stats(self, sandbox_id: UUID, session_id: UUID) -> tuple[int, int]:
        response = self._guest_json(
            sandbox_id,
            "upload-stats",
            _UploadStatsResponse,
            {"session_id": str(session_id)},
        )
        return response.file_count, response.total_size_bytes

    def write_files_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
    ) -> None:
        try:
            self._guest_json(
                sandbox_id,
                "push-managed",
                _StatusOk,
                {"mount_path": mount_path},
                stdin=_build_targz(files),
                timeout=BULK_TRANSFER_TIMEOUT_SECONDS,
            )
        except ValueError as error:
            raise FatalWriteError(str(error)) from error
        except SandboxExecError as error:
            if error.returncode is None:
                raise RetriableWriteError(str(error)) from error
            raise FatalWriteError(str(error)) from error

    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        return self._runtime.service_url(sandbox_id, port)

    def generate_document_preview(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        document_path: str,
        cache_dir: str,
        *,
        first_page_only: bool = False,
    ) -> tuple[list[str], bool]:
        session_root = f"/workspace/sessions/{session_id}"
        document_abs = f"{session_root}/{self._clean_relative_path(document_path)}"
        cache_abs = f"{session_root}/{self._clean_relative_path(cache_dir)}"
        command = document_preview_command(
            document_abs,
            cache_abs,
            session_root,
            first_page_only=first_page_only,
        )

        def run_command(args: list[str]) -> str:
            return self._run(sandbox_id, args, timeout=130)

        self._ensure_document_preview_bundle(sandbox_id, run_command)
        return parse_document_preview_response(run_command(command), session_root)

    def _load_serve_connection_info(
        self, sandbox_id: UUID
    ) -> ServeConnectionInfo | None:
        password = self._runtime.read_password(sandbox_id)
        if not password:
            raise RuntimeError("Craft VM has no OpenCode authentication secret")
        return ServeConnectionInfo(
            base_url=self._runtime.service_url(sandbox_id, OPENCODE_SERVE_PORT),
            password=password,
        )

    def stream_pod_logs(
        self,
        sandbox_id: UUID,
        *,
        container: str = "sandbox",
        tail_lines: int = 200,
    ) -> Iterator[str]:
        if container != "sandbox":
            raise ValueError("Only sandbox container logs are supported")
        yield from self._runtime.stream_logs(
            sandbox_id,
            tail_lines=tail_lines,
        )

    def _ensure_agents_md_attachments_section(
        self, sandbox_id: UUID, session_id: UUID
    ) -> None:
        session_path = f"/workspace/sessions/{session_id}"
        agents_md_path = f"{session_path}/AGENTS.md"
        attachments_content_b64 = base64.b64encode(
            ATTACHMENTS_SECTION_CONTENT.encode()
        ).decode()
        script = f"""
set -e
if [ -f {shlex.quote(agents_md_path)} ] && ! grep -q "## Attachments (PRIORITY)" {shlex.quote(agents_md_path)} 2>/dev/null; then
    printf '\\n\\n' >> {shlex.quote(agents_md_path)}
    echo {shlex.quote(attachments_content_b64)} | base64 -d >> {shlex.quote(agents_md_path)}
fi
"""
        try:
            self._run_script(sandbox_id, script)
        except Exception:
            logger.warning(
                "Failed to update AGENTS.md attachments section for session %s",
                session_id,
                exc_info=True,
            )

    @staticmethod
    def _clean_relative_path(path: str) -> str:
        value = Path(path.lstrip("/"))
        if ".." in value.parts or "\0" in path:
            raise ValueError("Path escapes session workspace")
        parts = [part for part in value.parts if part not in {"", "."}]
        return str(Path(*parts)) if parts else "."

    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
        *,
        attachments: list[PromptAttachment] | None = None,
        opencode_session_id: str | None = None,
        agent_provider: str | None = None,
        agent_model: str | None = None,
        on_opencode_session_resolved: Callable[[str], None] | None = None,
        should_interrupt: Callable[[], bool] | None = None,
        should_abort_on_teardown: Callable[[], bool] | None = None,
        turn_timeout_seconds: float | None = None,
    ) -> Generator[SandboxEvent, None, None]:
        """Stream typed sandbox events for one user message via
        opencode-serve.

        - ``opencode_session_id``: persistent serve session id; pass
          ``BuildSession.opencode_session_id`` or ``None`` to mint.
        - ``agent_provider`` / ``agent_model``: per-prompt model override;
          either ``None`` falls back to the loaded default.
        - ``on_opencode_session_resolved``: invoked with the resolved id
          when it differs from the caller's. Caller persists it so later
          turns don't orphan a fresh session each time.
        """
        yield from self._send_message_via_serve(
            sandbox_id,
            session_id,
            message,
            opencode_session_id,
            agent_provider,
            agent_model,
            attachments=attachments,
            on_opencode_session_resolved=on_opencode_session_resolved,
            should_interrupt=should_interrupt,
            should_abort_on_teardown=should_abort_on_teardown,
            turn_timeout_seconds=turn_timeout_seconds,
        )

    def send_subagent_message(
        self,
        sandbox_id: UUID,
        parent_session_id: UUID,
        subagent_opencode_session_id: str,
        message: str,
        agent_provider: str | None = None,
        agent_model: str | None = None,
    ) -> Generator[SandboxEvent, None, None]:
        """Stream a follow-up turn against an existing subagent (child)
        opencode session that was spawned under ``parent_session_id``.

        The child session shares the parent's session directory. Pass the
        parent session's ``agent_provider``/``agent_model`` so the follow-up
        uses the same model as the parent rather than the child session's own
        default.
        """
        yield from self.send_subagent_message_via_serve(
            sandbox_id,
            parent_session_id,
            subagent_opencode_session_id,
            message,
            agent_provider=agent_provider,
            agent_model=agent_model,
        )

    def stamp_turn_deadline(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        *,
        soft_budget_seconds: int,
        hard_cap_seconds: int,
    ) -> None:
        """Write the per-turn deadline stamp turn-budget.ts reads. Best-effort;
        written at turn start, never restamped by continuations. ``stale_after``
        self-invalidates the stamp past the hard cap so a failed next-turn
        write leaves the plugin inert instead of nagging a fresh turn."""
        now_ms = int(time.time() * 1000)
        soft_ms = now_ms + soft_budget_seconds * 1000
        hard_ms = now_ms + hard_cap_seconds * 1000
        try:
            self.write_sandbox_file(
                sandbox_id,
                f"sessions/{session_id}/{TURN_BUDGET_FILE_NAME}",
                json.dumps(
                    {
                        "soft_deadline_epoch_ms": soft_ms,
                        "final_deadline_epoch_ms": max(
                            soft_ms, hard_ms - TURN_FINAL_NOTICE_MARGIN_SECONDS * 1000
                        ),
                        "stale_after_epoch_ms": hard_ms,
                    }
                ),
            )
        except Exception:
            logger.warning(
                "Failed to stamp turn deadline for session %s",
                session_id,
                exc_info=True,
            )

    def clear_turn_deadline(self, sandbox_id: UUID, session_id: UUID) -> None:
        """Invalidate the stamp at normal turn end so a failed next-turn
        restamp can't inherit it. Call only while holding the prompt slot — a
        successor's fresh stamp must not be clobbered. Best-effort."""
        try:
            self.write_sandbox_file(
                sandbox_id,
                f"sessions/{session_id}/{TURN_BUDGET_FILE_NAME}",
                "{}",
            )
        except Exception:
            logger.warning(
                "Failed to clear turn deadline for session %s",
                session_id,
                exc_info=True,
            )

    def push_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
        timeout_s: float = 30.0,
    ) -> PushResult:
        """Push files to a single sandbox with retry."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.write_files_to_sandbox(
                    sandbox_id=sandbox_id,
                    mount_path=mount_path,
                    files=files,
                )
                return PushResult(targets=1, succeeded=1, failures=[])
            except FatalWriteError as e:
                return PushResult(
                    targets=1,
                    succeeded=0,
                    failures=[
                        PushFailure(
                            sandbox_id=sandbox_id,
                            reason="write_error",
                            detail=str(e),
                        )
                    ],
                )
            except RetriableWriteError:
                if attempt < max_retries - 1:
                    time.sleep(min(2**attempt, timeout_s / max_retries))
                    continue
                return PushResult(
                    targets=1,
                    succeeded=0,
                    failures=[
                        PushFailure(
                            sandbox_id=sandbox_id,
                            reason="timeout",
                            detail=f"Failed after {max_retries} retries",
                        )
                    ],
                )
            except Exception as e:
                logger.warning(
                    "Unexpected error pushing to sandbox %s: %s",
                    sandbox_id,
                    e,
                )
                return PushResult(
                    targets=1,
                    succeeded=0,
                    failures=[
                        PushFailure(
                            sandbox_id=sandbox_id,
                            reason="write_error",
                            detail=str(e),
                        )
                    ],
                )
        raise AssertionError("unreachable: all retries should return")

    def push_to_sandboxes(
        self,
        *,
        mount_path: str,
        sandbox_files: dict[UUID, FileSet],
        timeout_s: float = 30.0,
    ) -> PushResult:
        """Push files to multiple sandboxes in parallel.

        Caller owns user→sandbox resolution (via DB). This method only handles
        parallelism and result aggregation over push_to_sandbox.
        """
        if not sandbox_files:
            return PushResult(targets=0, succeeded=0, failures=[])

        all_failures: list[PushFailure] = []
        pushed = 0

        def _push_one(sandbox_id: UUID) -> PushResult:
            return self.push_to_sandbox(
                sandbox_id=sandbox_id,
                mount_path=mount_path,
                files=sandbox_files[sandbox_id],
                timeout_s=timeout_s,
            )

        with ThreadPoolExecutor(max_workers=min(len(sandbox_files), 10)) as pool:
            for result in pool.map(_push_one, sandbox_files):
                pushed += result.succeeded
                all_failures.extend(result.failures)

        if all_failures:
            logger.warning(
                "push_to_sandboxes: %d/%d targets failed for mount_path=%s",
                len(all_failures),
                len(sandbox_files),
                mount_path,
            )

        return PushResult(
            targets=len(sandbox_files),
            succeeded=pushed,
            failures=all_failures,
        )

    def _ensure_document_preview_bundle(
        self, sandbox_id: UUID, run_command: Callable[[list[str]], str]
    ) -> None:
        probe = [
            "/bin/sh",
            "-c",
            'test -r "$1/preview.py" && test -r "$1/office/soffice.py" && printf READY || printf MISSING',
            "sh",
            _DOCUMENT_PREVIEW_MOUNT,
        ]
        if run_command(probe).strip() == "READY":
            return
        result = self.push_to_sandbox(
            sandbox_id=sandbox_id,
            mount_path=_DOCUMENT_PREVIEW_MOUNT,
            files=_DOCUMENT_PREVIEW_FILES,
        )
        if result.succeeded != 1:
            raise RuntimeError("Document preview bundle deployment failed")
        if run_command(probe).strip() != "READY":
            raise RuntimeError("Document preview bundle deployment is incomplete")


class _StatusOk(BaseModel):
    status: str


class _DirectoryListingResponse(BaseModel):
    entries: list[FilesystemEntry]


_sandbox_manager_instance: SandboxManager | None = None
_sandbox_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    global _sandbox_manager_instance
    with _sandbox_manager_lock:
        if _sandbox_manager_instance is None:
            _sandbox_manager_instance = SandboxManager()
            logger.info("Using SandboxManager for sandbox operations")
    return _sandbox_manager_instance
