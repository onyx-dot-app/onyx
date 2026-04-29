"""Snapshot management for sandbox state persistence."""

import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import BinaryIO
from typing import IO
from uuid import uuid4

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import FileStore
from onyx.utils.logger import setup_logger

logger = setup_logger()

# File type for snapshot archives
SNAPSHOT_FILE_TYPE = "application/gzip"


class SnapshotManager:
    """Manages sandbox snapshot creation and restoration.

    Snapshots are tar.gz archives of the sandbox's outputs directory,
    stored using the file store abstraction (S3-compatible storage).

    Responsible for:
    - Creating snapshots of outputs directories
    - Restoring snapshots to target directories
    - Deleting snapshots from storage

    Two flavors of API:

    - Path-based: ``create_snapshot(sandbox_path, ...)`` and
      ``restore_snapshot(storage_path, target_path)``. Used by the local
      backend, which has direct filesystem access.
    - Stream-based: ``create_snapshot_from_stream(...)`` and
      ``restore_snapshot_to_stream(...)``. Used by container-backed
      backends (Docker, future Firecracker, etc.) where the bytes come
      from a `docker exec` socket. The path-based methods are thin
      wrappers around these.
    """

    def __init__(self, file_store: FileStore) -> None:
        """Initialize SnapshotManager with a file store.

        Args:
            file_store: The file store to use for snapshot storage
        """
        self._file_store = file_store

    @staticmethod
    def _build_storage_path(tenant_id: str, sandbox_id: str, snapshot_id: str) -> str:
        """Storage path for a snapshot tarball within the file store.

        Format: ``sandbox-snapshots/{tenant_id}/{sandbox_id}/{snapshot_id}.tar.gz``
        """
        return f"sandbox-snapshots/{tenant_id}/{sandbox_id}/{snapshot_id}.tar.gz"

    def _save_stream_to_file_store(
        self,
        stream: BinaryIO,
        sandbox_id: str,
        tenant_id: str,
        snapshot_id: str,
    ) -> tuple[str, int]:
        """Persist tarball bytes to the file store and return (storage_path, size).

        Streams the bytes through a temp file so we can both upload via the
        FileStore API (which wants a seekable IO) and report a size.
        """
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".tar.gz", delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name
                # Use shutil.copyfileobj so memory stays bounded for big snapshots
                shutil.copyfileobj(stream, tmp_file)

            size_bytes = Path(tmp_path).stat().st_size
            storage_path = self._build_storage_path(tenant_id, sandbox_id, snapshot_id)
            display_name = f"sandbox-snapshot-{sandbox_id}-{snapshot_id}.tar.gz"

            with open(tmp_path, "rb") as f:
                self._file_store.save_file(
                    content=f,
                    display_name=display_name,
                    file_origin=FileOrigin.SANDBOX_SNAPSHOT,
                    file_type=SNAPSHOT_FILE_TYPE,
                    file_id=storage_path,
                    file_metadata={
                        "sandbox_id": sandbox_id,
                        "tenant_id": tenant_id,
                        "snapshot_id": snapshot_id,
                    },
                )

            return storage_path, size_bytes
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to cleanup temp file {tmp_path}: {cleanup_error}"
                    )

    def create_snapshot_from_stream(
        self,
        stream: BinaryIO,
        sandbox_id: str,
        tenant_id: str,
    ) -> tuple[str, str, int]:
        """Persist an already-tarred snapshot stream to the file store.

        Used by container-backed backends that produce a tar archive via
        ``tar -czf -`` inside the container and stream the bytes back through
        the exec socket.

        Args:
            stream: Binary stream yielding the tar.gz bytes (will be read to EOF)
            sandbox_id: Sandbox identifier
            tenant_id: Tenant identifier for multi-tenant isolation

        Returns:
            Tuple of (snapshot_id, storage_path, size_bytes)

        Raises:
            RuntimeError: If snapshot upload fails
        """
        snapshot_id = str(uuid4())
        try:
            storage_path, size_bytes = self._save_stream_to_file_store(
                stream=stream,
                sandbox_id=sandbox_id,
                tenant_id=tenant_id,
                snapshot_id=snapshot_id,
            )
            logger.info(
                f"Created snapshot {snapshot_id} for sandbox {sandbox_id}, size: {size_bytes} bytes"
            )
            return snapshot_id, storage_path, size_bytes
        except Exception as e:
            logger.error(f"Failed to create snapshot for sandbox {sandbox_id}: {e}")
            raise RuntimeError(f"Failed to create snapshot: {e}") from e

    def restore_snapshot_to_stream(self, storage_path: str) -> IO[bytes]:
        """Open a snapshot from the file store as a binary stream.

        The caller is responsible for closing the returned stream and for
        consuming it (e.g. piping into ``tar -xzf -`` inside a container).

        Args:
            storage_path: The file store path of the snapshot

        Returns:
            A binary stream containing the tar.gz bytes

        Raises:
            RuntimeError: If the snapshot can't be opened
        """
        try:
            return self._file_store.read_file(storage_path, use_tempfile=True)
        except Exception as e:
            logger.error(f"Failed to open snapshot {storage_path}: {e}")
            raise RuntimeError(f"Failed to open snapshot: {e}") from e

    def create_snapshot(
        self,
        sandbox_path: Path,
        sandbox_id: str,
        tenant_id: str,
    ) -> tuple[str, str, int]:
        """Create a snapshot of the outputs directory.

        Creates a tar.gz archive of the sandbox's outputs directory
        and uploads it to the file store.

        Args:
            sandbox_path: Path to the sandbox directory
            sandbox_id: Sandbox identifier
            tenant_id: Tenant identifier for multi-tenant isolation

        Returns:
            Tuple of (snapshot_id, storage_path, size_bytes)

        Raises:
            FileNotFoundError: If outputs directory doesn't exist
            RuntimeError: If snapshot creation fails
        """
        outputs_path = sandbox_path / "outputs"

        if not outputs_path.exists():
            raise FileNotFoundError(f"Outputs directory not found: {outputs_path}")

        # Create tar.gz in temp location, then hand to the stream-based path
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".tar.gz", delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name

            with tarfile.open(tmp_path, "w:gz") as tar:
                tar.add(outputs_path, arcname="outputs")

            with open(tmp_path, "rb") as f:
                return self.create_snapshot_from_stream(
                    stream=f,
                    sandbox_id=sandbox_id,
                    tenant_id=tenant_id,
                )
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to cleanup temp file {tmp_path}: {cleanup_error}"
                    )

    def restore_snapshot(
        self,
        storage_path: str,
        target_path: Path,
    ) -> None:
        """Restore a snapshot to target directory.

        Downloads the snapshot from file store and extracts the outputs/
        directory to the target path.

        Args:
            storage_path: The file store path of the snapshot
            target_path: Directory to extract the snapshot into

        Raises:
            FileNotFoundError: If snapshot doesn't exist in file store
            RuntimeError: If restoration fails
        """
        tmp_path: str | None = None
        file_io = None
        try:
            file_io = self.restore_snapshot_to_stream(storage_path)

            with tempfile.NamedTemporaryFile(
                suffix=".tar.gz", delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name
                shutil.copyfileobj(file_io, tmp_file)

            target_path.mkdir(parents=True, exist_ok=True)

            with tarfile.open(tmp_path, "r:gz") as tar:
                # Use data filter for safe extraction (prevents path traversal)
                # Available in Python 3.11.4+
                try:
                    tar.extractall(target_path, filter="data")
                except TypeError:
                    # Fallback for older Python versions without filter support
                    for member in tar.getmembers():
                        member_path = Path(target_path) / member.name
                        try:
                            member_path.resolve().relative_to(target_path.resolve())
                        except ValueError:
                            raise RuntimeError(
                                f"Path traversal attempt detected: {member.name}"
                            )
                    tar.extractall(target_path)

            logger.info(f"Restored snapshot from {storage_path} to {target_path}")

        except Exception as e:
            logger.error(f"Failed to restore snapshot {storage_path}: {e}")
            raise RuntimeError(f"Failed to restore snapshot: {e}") from e
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to cleanup temp file {tmp_path}: {cleanup_error}"
                    )
            try:
                if file_io:
                    file_io.close()
            except Exception:
                pass

    def delete_snapshot(self, storage_path: str) -> None:
        """Delete snapshot from file store.

        Args:
            storage_path: The file store path of the snapshot to delete

        Raises:
            RuntimeError: If deletion fails (other than file not found)
        """
        try:
            self._file_store.delete_file(storage_path)
            logger.info(f"Deleted snapshot: {storage_path}")
        except Exception as e:
            # Log but don't fail if snapshot doesn't exist
            logger.warning(f"Failed to delete snapshot {storage_path}: {e}")
            raise RuntimeError(f"Failed to delete snapshot: {e}") from e

    def get_snapshot_size(self, storage_path: str) -> int | None:
        """Get the size of a snapshot in bytes.

        Args:
            storage_path: The file store path of the snapshot

        Returns:
            Size in bytes, or None if not available
        """
        return self._file_store.get_file_size(storage_path)
