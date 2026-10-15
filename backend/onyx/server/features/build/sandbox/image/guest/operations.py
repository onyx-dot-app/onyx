"""Guest filesystem operations executed without root privileges."""

import os
import select
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO
from uuid import UUID

from . import SESSIONS_ROOT
from .filesystem import list_session_directory
from .input import FramedInput
from .models import (
    EmptyRequest,
    PathRequest,
    RunRequest,
    SessionRequest,
    UploadRequest,
    WriteRequest,
)
from .opencode_history import (
    create_opencode_history_archive_file,
    restore_opencode_history_archive,
)
from .outputs_manifest import build_outputs_manifest
from .snapshot import (
    _remove_workspace_tree,
    _safe_session_path,
    iter_snapshot_archive,
    restore_snapshot,
)

MAX_INPUT_BYTES = 100 * 1024 * 1024
MAX_STDERR_BYTES = 16 * 1024


def spool_stdin(
    source: FramedInput, destination: IO[bytes], *, max_bytes: int = MAX_INPUT_BYTES
) -> None:
    for chunk in source.chunks(max_bytes=max_bytes):
        destination.write(chunk)
    destination.seek(0)


def session_file(session_id: UUID, path: str, *, read_library: bool = False) -> Path:
    relative = Path(path.lstrip("/"))
    if "\x00" in path or ".." in relative.parts or relative == Path("."):
        raise ValueError("invalid session file path")
    root = _safe_session_path(session_id, create=False)
    candidate = root / relative
    resolved = candidate.resolve()
    if resolved.is_relative_to(root.resolve()):
        return candidate
    library = Path("/workspace/managed/user_library")
    if (
        read_library
        and relative.parts[0] == "user_library"
        and (root / "user_library").is_symlink()
        and (root / "user_library").readlink() == library
        and resolved.is_relative_to(library.resolve())
    ):
        return candidate
    raise ValueError("file path escapes session")


def read_file(request: PathRequest) -> None:
    path = session_file(request.session_id, request.path, read_library=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("path is not a regular file")
        if metadata.st_size > MAX_INPUT_BYTES:
            raise ValueError("file exceeds 100 MiB download limit")
        shutil.copyfileobj(source, sys.stdout.buffer, length=1024 * 1024)


def upload_file(request: UploadRequest, source: IO[bytes]) -> dict[str, str]:
    filename = request.filename
    if (
        not filename
        or filename in {".", ".."}
        or Path(filename).name != filename
        or "\x00" in filename
    ):
        raise ValueError("invalid attachment filename")
    directory = session_file(request.session_id, "attachments/placeholder").parent
    directory.mkdir(parents=True, exist_ok=True)
    stem, suffix = Path(filename).stem, Path(filename).suffix
    index = 0
    while True:
        name = filename if index == 0 else f"{stem}_{index}{suffix}"
        try:
            descriptor = os.open(
                directory / name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o644,
            )
            break
        except FileExistsError:
            index += 1
    with os.fdopen(descriptor, "wb") as destination:
        shutil.copyfileobj(source, destination)
    return {"path": f"attachments/{name}"}


def write_file(request: WriteRequest, source: IO[bytes]) -> None:
    if request.session_id is None:
        relative = Path(request.path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) < 3
            or relative.parts[0] != "sessions"
        ):
            raise ValueError("write path must be under sessions/<UUID>/")
        session_id = UUID(relative.parts[1])
        path = str(Path(*relative.parts[2:]))
    else:
        session_id, path = request.session_id, request.path
    destination = session_file(session_id, path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o644,
    )
    with os.fdopen(descriptor, "wb") as target:
        if not stat.S_ISREG(os.fstat(target.fileno()).st_mode):
            raise ValueError("path is not a regular file")
        shutil.copyfileobj(source, target)


def run(request: RunRequest, source: IO[bytes], *, deadline: float) -> int:
    if deadline <= time.monotonic():
        sys.stderr.buffer.write(b"\ncommand timed out\n")
        return 124
    stderr = bytearray()
    process = subprocess.Popen(
        request.argv,
        cwd=request.cwd,
        stdin=source,
        stdout=sys.stdout.buffer,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        if process.stderr is None:
            raise RuntimeError("command stderr pipe not available")
        pipe = process.stderr

        def drain_stderr() -> None:
            with pipe:
                while chunk := pipe.read(8192):
                    stderr.extend(chunk)
                    del stderr[:-MAX_STDERR_BYTES]

        reader = threading.Thread(target=drain_stderr, daemon=True)
        reader.start()
        try:
            code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
            if code != 0:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            code = 124
            stderr.extend(b"\ncommand timed out\n")
        reader.join(timeout=1)
        sys.stderr.buffer.write(stderr[-MAX_STDERR_BYTES:])
        return code if code >= 0 else 128 - code
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise


def stop_session_preview(root: Path) -> None:
    if sys.platform != "linux":
        raise RuntimeError("session preview cleanup requires Linux")
    try:
        descriptor = os.open(
            root / "nextjs.pid", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
    except (FileNotFoundError, NotADirectoryError):
        return
    with os.fdopen(descriptor, "r") as record:
        if not stat.S_ISREG(os.fstat(record.fileno()).st_mode):
            return
        value = record.read(32).strip()
    if not value.isdecimal() or not 1 < (pid := int(value)) <= 2**31 - 1:
        return
    try:
        pid_fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        try:
            if Path(f"/proc/{pid}/cwd").readlink() != root / "outputs/web":
                return
            owns_process_group = os.getpgid(pid) == pid
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            return
        try:
            signal.pidfd_send_signal(pid_fd, signal.SIGTERM)
            if not select.select([pid_fd], [], [], 5)[0]:
                if owns_process_group:
                    os.killpg(pid, signal.SIGKILL)
                else:
                    signal.pidfd_send_signal(pid_fd, signal.SIGKILL)
                if not select.select([pid_fd], [], [], 2)[0]:
                    raise RuntimeError("session preview did not stop")
        except ProcessLookupError:
            pass
    finally:
        os.close(pid_fd)


def execute(
    operation: str, metadata: str, source: IO[bytes], archive_path: Path
) -> object:
    if operation == "list-workspaces":
        EmptyRequest.model_validate_json(metadata)
        sessions = []
        for path in SESSIONS_ROOT.iterdir():
            if path.is_dir() and not path.is_symlink():
                try:
                    sessions.append(str(UUID(path.name)))
                except ValueError:
                    continue
        return {"session_ids": sorted(sessions)}
    if operation == "snapshot-history":
        EmptyRequest.model_validate_json(metadata)
        history_archive = create_opencode_history_archive_file()
        if history_archive is not None:
            try:
                with history_archive.open("rb") as history:
                    shutil.copyfileobj(history, sys.stdout.buffer)
            finally:
                history_archive.unlink(missing_ok=True)
        return None
    if operation == "_restore-history":
        EmptyRequest.model_validate_json(metadata)
        restore_opencode_history_archive(archive_path)
        return None
    if operation == "upload-file":
        return upload_file(UploadRequest.model_validate_json(metadata), source)
    if operation == "write-file":
        write_file(WriteRequest.model_validate_json(metadata), source)
        return {"status": "ok"}
    if operation in {"list-directory", "read-file", "delete-file"}:
        request = PathRequest.model_validate_json(metadata)
        if operation == "list-directory":
            return list_session_directory(request.session_id, request.path).model_dump()
        if operation == "read-file":
            read_file(request)
            return None
        path = session_file(request.session_id, request.path)
        if not path.is_file():
            return {"deleted": False}
        path.unlink()
        return {"deleted": True}
    return execute_session(
        operation, SessionRequest.model_validate_json(metadata), archive_path
    )


def execute_session(
    operation: str, request: SessionRequest, archive_path: Path
) -> object:
    if operation == "outputs-manifest":
        return build_outputs_manifest(request.session_id).model_dump()
    if operation == "workspace-exists":
        root = _safe_session_path(request.session_id, create=False)
        return {
            "exists": root.is_dir()
            and (root / "outputs").is_dir()
            and not (root / ".setup-in-progress").exists()
        }
    if operation == "cleanup-workspace":
        root = _safe_session_path(request.session_id, create=False)
        if root.exists():
            stop_session_preview(root)
            _remove_workspace_tree(root)
        return {"status": "ok"}
    if operation == "upload-stats":
        directory = session_file(request.session_id, "attachments/placeholder").parent
        entries = list(directory.iterdir()) if directory.is_dir() else []
        regular = [
            entry for entry in entries if entry.is_file() and not entry.is_symlink()
        ]
        return {
            "file_count": len(regular),
            "total_size_bytes": sum(entry.stat().st_size for entry in regular),
        }
    if operation == "create-snapshot":
        for chunk in iter_snapshot_archive(request.session_id):
            sys.stdout.buffer.write(chunk)
        return None
    if operation == "restore-snapshot":
        restore_snapshot(request.session_id, archive_path)
        return {"status": "ok"}
    raise ValueError(f"unknown operation: {operation}")
