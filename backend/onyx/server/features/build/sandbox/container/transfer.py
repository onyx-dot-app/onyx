"""Session saves of container sandboxes: the api_server streams the guest
daemon's CaptureSession archive into the file store, and a restore streams
it back into RestoreSession. No presigned URLs, so any file store works.
The archive format is the Firecracker one: a save restores on either
backend."""

import hashlib
import tempfile
from collections.abc import Callable
from typing import IO
from uuid import UUID

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.microvm.daemon_client import SandboxDaemonClient
from onyx.microvm.models import DaemonCaptureSummary
from onyx.server.features.build.sandbox.firecracker.models import (
    CapturedArchive,
    SessionSave,
)
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    ARCHIVE_DISPLAY_NAME,
    ARCHIVE_FILE_TYPE,
    ArchiveStorage,
    SessionSaveCancelledError,
    SessionSaveError,
    SessionTransfer,
)

# The spool keeps an archive in memory up to this size, then on disk.
_SPOOL_MEMORY_BYTES = 8 << 20


class FileStoreArchives(ArchiveStorage):
    """Session archives in the deployment file store, moved by the
    api_server."""

    def __init__(self, store: FileStore) -> None:
        self._store = store

    def save(self, data: IO[bytes]) -> str:
        return self._store.save_file(
            content=data,
            display_name=ARCHIVE_DISPLAY_NAME,
            file_origin=FileOrigin.SANDBOX_SNAPSHOT,
            file_type=ARCHIVE_FILE_TYPE,
        )

    def open(self, file_id: str) -> IO[bytes]:
        return self._store.read_file(file_id, use_tempfile=True)

    def delete(self, file_id: str) -> None:
        self._store.delete_file(file_id, error_on_missing=False)


def default_file_store_archives() -> FileStoreArchives:
    return FileStoreArchives(get_default_file_store())


class FileStoreSessionTransfer(SessionTransfer):
    def __init__(
        self, daemon: SandboxDaemonClient, archives: FileStoreArchives
    ) -> None:
        self._daemon = daemon
        self._archives = archives

    def capture(
        self,
        *,
        session_id: UUID,
        roots: list[str],
        cancelled: Callable[[], bool] | None,
    ) -> CapturedArchive:
        digest = hashlib.sha256()
        summary: DaemonCaptureSummary | None = None
        with tempfile.SpooledTemporaryFile(max_size=_SPOOL_MEMORY_BYTES) as spool:
            stream = self._daemon.capture_session(
                session_id=str(session_id), roots=roots
            )
            try:
                while True:
                    if cancelled is not None and cancelled():
                        raise SessionSaveCancelledError(
                            f"save of {session_id} cancelled"
                        )
                    chunk = next(stream)
                    digest.update(chunk)
                    spool.write(chunk)
            except StopIteration as end:
                summary = end.value
            finally:
                stream.close()
            size = spool.tell()
            if summary is None:
                raise RuntimeError("Bug: a capture ended without its summary")
            if summary.sha256 != digest.hexdigest() or summary.size_bytes != size:
                raise SessionSaveError(
                    f"the archive of session {session_id} does not match its summary"
                )
            spool.seek(0)
            file_id = self._archives.save(spool)
        return CapturedArchive(
            file_id=file_id,
            size_bytes=size,
            sha256=summary.sha256,
            roots=summary.roots,
        )

    def restore(self, *, session_id: UUID, save: SessionSave) -> None:
        if save.file_id is None:
            raise RuntimeError("Bug: a restore of a save without an archive")
        data = self._archives.open(save.file_id)
        try:
            self._daemon.restore_session(
                session_id=str(session_id),
                data=data,
                size_bytes=save.size_bytes,
                sha256=save.sha256,
                roots=save.roots,
            )
        finally:
            data.close()
