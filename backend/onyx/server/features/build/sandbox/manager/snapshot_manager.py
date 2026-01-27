"""Snapshot management for sandbox state persistence."""

import tarfile
import tempfile
from pathlib import Path
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
    """

    def __init__(self, file_store: FileStore) -> None:
        """Initialize SnapshotManager with a file store.

        Args:
            file_store: The file store to use for snapshot storage
        """
        self._file_store = file_store

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
        snapshot_id = str(uuid4())
        outputs_path = sandbox_path / "outputs"

        if not outputs_path.exists():
            raise FileNotFoundError(f"Outputs directory not found: {outputs_path}")

        # Create tar.gz in temp location
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".tar.gz", delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name

            # Create the tar archive
            with tarfile.open(tmp_path, "w:gz") as tar:
                tar.add(outputs_path, arcname="outputs")

            # Get size
            size_bytes = Path(tmp_path).stat().st_size

            # Generate storage path for file store
            # Format: sandbox-snapshots/{tenant_id}/{sandbox_id}/{snapshot_id}.tar.gz
            storage_path = (
                f"sandbox-snapshots/{tenant_id}/{sandbox_id}/{snapshot_id}.tar.gz"
            )
            display_name = f"sandbox-snapshot-{sandbox_id}-{snapshot_id}.tar.gz"

            # Upload to file store
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

            logger.info(
                f"Created snapshot {snapshot_id} for sandbox {sandbox_id}, "
                f"size: {size_bytes} bytes"
            )

            return snapshot_id, storage_path, size_bytes

        except Exception as e:
            logger.error(f"Failed to create snapshot for sandbox {sandbox_id}: {e}")
            raise RuntimeError(f"Failed to create snapshot: {e}") from e
        finally:
            # Cleanup temp file
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
            # Download from file store
            file_io = self._file_store.read_file(storage_path, use_tempfile=True)

            # Write to temp file for tarfile extraction
            with tempfile.NamedTemporaryFile(
                suffix=".tar.gz", delete=False
            ) as tmp_file:
                tmp_path = tmp_file.name
                # Read from the IO object and write to temp file
                content = file_io.read()
                tmp_file.write(content)

            # Ensure target path exists
            target_path.mkdir(parents=True, exist_ok=True)

            # Extract with security filter
            with tarfile.open(tmp_path, "r:gz") as tar:
                # Use data filter for safe extraction (prevents path traversal)
                # Available in Python 3.11.4+
                try:
                    tar.extractall(target_path, filter="data")
                except TypeError:
                    # Fallback for older Python versions without filter support
                    # Manually validate paths for security
                    for member in tar.getmembers():
                        # Check for path traversal attempts
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
            # Cleanup temp file
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to cleanup temp file {tmp_path}: {cleanup_error}"
                    )
            # Close the file IO if it's still open
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
