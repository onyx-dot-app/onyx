"""Snapshot management for sandbox state persistence."""

import tempfile
from pathlib import Path
from typing import IO
from uuid import uuid4

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import FileStore
from onyx.utils.logger import setup_logger

logger = setup_logger()

# File type for snapshot archives
SNAPSHOT_FILE_TYPE = "application/gzip"
_SNAPSHOT_COPY_CHUNK_BYTES = 8 * 1024 * 1024
_OPENCODE_HISTORY_FILE_NAME = "opencode-history.tar.gz"


def _copy_snapshot_stream(
    source: IO[bytes],
    target: IO[bytes],
) -> int:
    size_bytes = 0
    while True:
        chunk = source.read(_SNAPSHOT_COPY_CHUNK_BYTES)
        if not chunk:
            break
        size_bytes += len(chunk)
        target.write(chunk)
    return size_bytes


class SnapshotManager:
    """Manages sandbox snapshot creation and restoration.

    Snapshots are tar.gz archives of sandbox session state, stored using the
    file store abstraction.

    Responsible for:
    - Persisting sandbox-produced snapshot streams
    - Restoring stored snapshot streams back to sandbox managers
    - Deleting snapshots from storage
    """

    def __init__(self, file_store: FileStore) -> None:
        """Initialize SnapshotManager with a file store.

        Args:
            file_store: The file store to use for snapshot storage
        """
        self._file_store = file_store

    def _persist_archive_to_file_store(
        self,
        *,
        stream: IO[bytes],
        storage_path: str,
        display_name: str,
        metadata: dict[str, str],
        reject_empty: bool = False,
    ) -> int:
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".tar.gz", delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name
                size_bytes = _copy_snapshot_stream(
                    stream,
                    tmp_file,
                )
                if reject_empty and size_bytes == 0:
                    raise RuntimeError("snapshot stream was empty")

            with open(tmp_path, "rb") as f:
                self._file_store.save_file(
                    content=f,
                    display_name=display_name,
                    file_origin=FileOrigin.SANDBOX_SNAPSHOT,
                    file_type=SNAPSHOT_FILE_TYPE,
                    file_id=storage_path,
                    file_metadata=metadata,
                )
            return size_bytes
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as cleanup_error:
                    logger.warning(
                        "Failed to cleanup temp file %s: %s",
                        tmp_path,
                        cleanup_error,
                    )

    def persist_snapshot_from_stream(
        self,
        stream: IO[bytes],
        sandbox_id: str,
        tenant_id: str,
    ) -> tuple[str, str, int]:
        """Persist an already-built tar.gz byte stream as a snapshot.

        This is used by backends (e.g. Docker) that produce the tar stream
        inside the sandbox container via exec and stream it back to the
        api_server, so no on-host outputs directory ever exists. The caller
        is responsible for producing a valid tar.gz stream.

        Args:
            stream: Binary, readable stream of tar.gz bytes.
            sandbox_id: Sandbox identifier (string form).
            tenant_id: Tenant identifier for multi-tenant isolation.

        Returns:
            Tuple of (snapshot_id, storage_path, size_bytes).
        """
        snapshot_id = str(uuid4())
        storage_path = (
            f"sandbox-snapshots/{tenant_id}/{sandbox_id}/{snapshot_id}.tar.gz"
        )
        display_name = f"sandbox-snapshot-{sandbox_id}-{snapshot_id}.tar.gz"
        metadata = {
            "sandbox_id": sandbox_id,
            "tenant_id": tenant_id,
            "snapshot_id": snapshot_id,
        }

        # Spool to a temp file so file store implementations receive a seekable
        # stream and we can report exact snapshot metadata.
        try:
            size_bytes = self._persist_archive_to_file_store(
                stream=stream,
                storage_path=storage_path,
                display_name=display_name,
                metadata=metadata,
            )

            logger.info(
                "Created snapshot %s for sandbox %s, size: %s bytes",
                snapshot_id,
                sandbox_id,
                size_bytes,
            )
            return snapshot_id, storage_path, size_bytes
        except Exception as e:
            logger.error(
                "Failed to create streamed snapshot for sandbox %s: %s",
                sandbox_id,
                e,
            )
            raise RuntimeError(f"Failed to create snapshot: {e}") from e

    @staticmethod
    def opencode_history_storage_path(tenant_id: str, sandbox_id: str) -> str:
        return (
            f"sandbox-snapshots/{tenant_id}/{sandbox_id}/{_OPENCODE_HISTORY_FILE_NAME}"
        )

    def has_opencode_history_snapshot(self, tenant_id: str, sandbox_id: str) -> bool:
        return self._file_store.has_file(
            file_id=self.opencode_history_storage_path(tenant_id, sandbox_id),
            file_origin=FileOrigin.SANDBOX_SNAPSHOT,
            file_type=SNAPSHOT_FILE_TYPE,
        )

    def persist_opencode_snapshot_from_stream(
        self,
        stream: IO[bytes],
        sandbox_id: str,
        tenant_id: str,
    ) -> tuple[str, int]:
        storage_path = self.opencode_history_storage_path(tenant_id, sandbox_id)
        display_name = f"sandbox-opencode-history-{sandbox_id}.tar.gz"
        metadata = {
            "sandbox_id": sandbox_id,
            "tenant_id": tenant_id,
            "snapshot_kind": "opencode_history",
        }

        try:
            size_bytes = self._persist_archive_to_file_store(
                stream=stream,
                storage_path=storage_path,
                display_name=display_name,
                metadata=metadata,
                reject_empty=True,
            )

            logger.info(
                "Created opencode history snapshot for sandbox %s, size: %s bytes",
                sandbox_id,
                size_bytes,
            )
            return storage_path, size_bytes
        except Exception as e:
            logger.error(
                "Failed to create opencode history snapshot for sandbox %s: %s",
                sandbox_id,
                e,
            )
            raise RuntimeError(
                f"Failed to create opencode history snapshot: {e}"
            ) from e

    def delete_opencode_history_snapshot(self, tenant_id: str, sandbox_id: str) -> None:
        storage_path = self.opencode_history_storage_path(tenant_id, sandbox_id)
        self._file_store.delete_file(storage_path, error_on_missing=False)

    def restore_snapshot_to_stream(
        self,
        storage_path: str,
        write_stream: IO[bytes],
    ) -> None:
        """Stream a stored snapshot's bytes into a caller-provided writer.

        Used by backends (e.g. Docker) that extract the archive inside the
        sandbox container by piping bytes into a remote ``tar -x`` process,
        avoiding an on-host extraction step.

        Args:
            storage_path: The file store path of the snapshot.
            write_stream: Binary writable stream the bytes are written into.
        """
        file_io = None
        try:
            file_io = self._file_store.read_file(storage_path, use_tempfile=True)
            _copy_snapshot_stream(
                file_io,
                write_stream,
            )
            logger.info("Streamed snapshot %s to caller writer", storage_path)
        except Exception as e:
            logger.error("Failed to stream snapshot %s to writer: %s", storage_path, e)
            raise RuntimeError(f"Failed to stream snapshot: {e}") from e
        finally:
            try:
                if file_io:
                    file_io.close()
            except Exception:
                pass

    def delete_snapshot(self, storage_path: str) -> None:
        """Delete a snapshot's blob from the file store.

        Idempotent: a missing blob is treated as already-deleted (not an error),
        so a caller retrying after a partial failure can still drop its DB row
        without the blob and row leaking out of sync.

        Args:
            storage_path: The file store path of the snapshot to delete

        Raises:
            RuntimeError: If deletion fails for a reason other than the blob
                already being gone.
        """
        try:
            self._file_store.delete_file(storage_path, error_on_missing=False)
            logger.info("Deleted snapshot: %s", storage_path)
        except Exception as e:
            logger.warning("Failed to delete snapshot %s: %s", storage_path, e)
            raise RuntimeError(f"Failed to delete snapshot: {e}") from e
