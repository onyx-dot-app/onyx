from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import BLOB_STORAGE_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.storage_file_document import (
    build_storage_file_document,
)
from onyx.connectors.exceptions import (
    CredentialInvalidError,
    UnreachableValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
)
from onyx.connectors.smb.access import SmbAccessWalker, build_access_walker
from onyx.connectors.smb.config import (
    DEFAULT_SMB_PORT,
    SmbConnectorConfig,
    normalize_path,
)
from onyx.connectors.smb.models import (
    EmailAttribute,
    SmbCheckpoint,
    SmbEntry,
    SmbPendingFolder,
)
from onyx.connectors.smb.source_operations import (
    CONFIG_HOST,
    CONFIG_PORT,
    CONFIG_REQUIRE_ENCRYPTION,
    CONFIG_SHARE,
    SmbAccessDeniedError,
    SmbNotFoundError,
    SmbSourceOperations,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.file_types import is_indexable_file_type
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

DOCUMENT_ID_SCHEME = "smb://"
# The metadata key of a file's UNC path. A browser blocks file links from a
# web page, so the path is shown as text and the document has no link.
PATH_METADATA_KEY = "path"
# Files read per checkpoint step.
FILES_PER_STEP = 100
SLIM_BATCH_SIZE = 1000
# A deeper folder is a loop. A link that the server itself follows shows as a
# plain folder, not as a reparse point, so only the depth gives it away.
MAX_FOLDER_DEPTH = 100
# Office lock files, and the files Explorer writes into folders.
_LOCK_FILE_PREFIX = "~$"
_SYSTEM_FILE_NAMES = frozenset({"thumbs.db", "desktop.ini"})

# Failures that stop the attempt: the credential or the server itself, not
# one file.
_ATTEMPT_ERRORS = (CredentialInvalidError, UnreachableValidationError)


def join_path(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


def parent_path(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def is_skipped_entry(entry: SmbEntry, *, index_offline_files: bool) -> bool:
    """Entries that no walk follows or reads."""
    # A junction can point above itself, which loops the walk.
    if entry.is_reparse_point:
        logger.debug("Skipping reparse point %s", entry.name)
        return True
    if entry.is_directory:
        return False
    if entry.is_offline and not index_offline_files:
        logger.debug("Skipping offline file %s", entry.name)
        return True
    name: str = entry.name.lower()
    return name.startswith(_LOCK_FILE_PREFIX) or name in _SYSTEM_FILE_NAMES


def is_indexable_file(
    entry: SmbEntry, *, allow_images: bool, size_threshold: int
) -> bool:
    """Indexing, the slim listing and the file-read check admit the same
    files."""
    if entry.is_directory:
        return False
    if not is_indexable_file_type(entry.name, None, allow_images=allow_images):
        logger.debug("Skipping file type that is not indexed: %s", entry.name)
        return False
    if entry.size > size_threshold:
        logger.info(
            "Skipping %s: %s bytes is over the %s byte limit",
            entry.name,
            entry.size,
            size_threshold,
        )
        return False
    return True


def moved_since(
    folder: SmbEntry, parent_last_write_time: datetime | None, start: datetime
) -> bool:
    """Whether the folder may have a new path since ``start``. A rename or a
    move changes the folder's change time and its parent's last write time,
    and leaves the files below untouched, so no timestamp of theirs tells.
    A folder that only got a new entry also has a new change time, so the
    parent's last write time narrows the answer. Neither time has an upper
    bound: later changes can move both past the end of the poll window."""
    if folder.change_time < start:
        return False
    if folder.change_time != folder.last_write_time:
        return True
    return parent_last_write_time is None or parent_last_write_time >= start


class SmbConnector(
    CheckpointedConnector[SmbCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
    Resolver,
    CredentialsConnector,
):
    def __init__(
        self,
        host: str,
        share: str,
        path_prefix: str = "",
        excluded_paths: list[str] | None = None,
        require_encryption: bool = True,
        index_offline_files: bool = False,
        port: int = DEFAULT_SMB_PORT,
        email_attribute: EmailAttribute = EmailAttribute.MAIL,
        share_permissions_confirmed: bool = False,
    ) -> None:
        self.host = host
        self.share = share
        self.path_prefix = normalize_path(path_prefix)
        self.excluded_paths: list[str] = sorted(
            {normalize_path(path) for path in excluded_paths or []} - {""}
        )
        self.require_encryption = require_encryption
        self.index_offline_files = index_offline_files
        self.port = port
        self.email_attribute = EmailAttribute(email_attribute)
        self.share_permissions_confirmed = share_permissions_confirmed
        self.size_threshold: int = BLOB_STORAGE_SIZE_THRESHOLD
        self._allow_images = False
        self._ops: SmbSourceOperations | None = None

    @property
    def ops(self) -> SmbSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("Windows file share")
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use set_credentials_provider with this connector.")

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = SmbSourceOperations(
            credentials_provider=credentials_provider,
            connector_specific_config={
                CONFIG_HOST: self.host,
                CONFIG_SHARE: self.share,
                CONFIG_PORT: self.port,
                CONFIG_REQUIRE_ENCRYPTION: self.require_encryption,
            },
        )

    def config(self) -> SmbConnectorConfig:
        """The connector's settings as the checks read them."""
        return SmbConnectorConfig(
            host=self.host,
            share=self.share,
            path_prefix=self.path_prefix,
            excluded_paths=self.excluded_paths or None,
            require_encryption=self.require_encryption,
            index_offline_files=self.index_offline_files,
            port=self.port,
            email_attribute=self.email_attribute,
            share_permissions_confirmed=self.share_permissions_confirmed,
        )

    def set_allow_images(self, value: bool) -> None:
        self._allow_images = value

    def validate_connector_settings(self) -> None:
        """Signs in and lists the path prefix: the gateway names a rejected
        account, a missing share or folder, or missing read access."""
        self.ops.list_folder(path=self.path_prefix)

    def _root_id(self) -> str:
        """Host names repeat across networks only by an admin's choice, and
        DNS ignores their case."""
        return f"{DOCUMENT_ID_SCHEME}{self.host.lower()}/{self.share}"

    def document_id(self, path: str) -> str:
        return f"{self._root_id()}/{path}" if path else self._root_id()

    def unc_path(self, path: str) -> str:
        root: str = f"\\\\{self.host}\\{self.share}"
        return f"{root}\\{path.replace('/', '\\')}" if path else root

    def _folder_node(self, path: str) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=self.document_id(path),
            raw_parent_id=self.document_id(parent_path(path)) if path else None,
            display_name=path.rsplit("/", 1)[-1] if path else self.share,
            node_type=HierarchyNodeType.FOLDER,
        )

    @staticmethod
    def _folders_to(path: str) -> list[str]:
        """The share root and every folder down to ``path``, parents first."""
        parts: list[str] = path.split("/") if path else []
        return ["", *("/".join(parts[: depth + 1]) for depth in range(len(parts)))]

    def _is_excluded(self, path: str) -> bool:
        """Windows compares names without regard to case."""
        folded: str = path.casefold()
        return any(
            folded == excluded.casefold()
            or folded.startswith(f"{excluded.casefold()}/")
            for excluded in self.excluded_paths
        )

    def _is_skipped(self, entry: SmbEntry, path: str) -> bool:
        if entry.is_directory and path.count("/") >= MAX_FOLDER_DEPTH:
            logger.warning(
                "Skipping %s: it is more than %s folders deep, which is a loop",
                path,
                MAX_FOLDER_DEPTH,
            )
            return True
        return self._is_excluded(path) or is_skipped_entry(
            entry, index_offline_files=self.index_offline_files
        )

    def _is_indexable(self, entry: SmbEntry) -> bool:
        return is_indexable_file(
            entry, allow_images=self._allow_images, size_threshold=self.size_threshold
        )

    def _failure(self, path: str, error: Exception) -> ConnectorFailure:
        return ConnectorFailure(
            failed_document=DocumentFailure(document_id=self.document_id(path)),
            failure_message=f"Failed to index {self.unc_path(path)}: {error}",
            exception=error,
        )

    def _read_document(self, path: str, entry: SmbEntry) -> Document | None:
        """The file as a document. None when it grew past the size limit or
        holds nothing to index."""
        file = self.ops.read_file(path=path, max_bytes=self.size_threshold)
        if file.content is None:
            logger.info("Skipping %s: it grew past the size limit", path)
            return None
        document: Document | None = build_storage_file_document(
            file_bytes=file.content,
            file_name=entry.name,
            document_id=self.document_id(path),
            source=DocumentSource.SMB,
            link=None,
            last_modified=entry.last_write_time,
            image_file_id=quote(self.document_id(path), safe=""),
            raw_file_callback=self.raw_file_callback,
            include_embedded_images=self._allow_images,
        )
        if document is not None:
            document.parent_hierarchy_raw_node_id = self.document_id(parent_path(path))
            document.metadata = {
                **document.metadata,
                PATH_METADATA_KEY: self.unc_path(path),
            }
        return document

    def _index_file(
        self, path: str, entry: SmbEntry
    ) -> Document | ConnectorFailure | None:
        try:
            return self._read_document(path, entry)
        except _ATTEMPT_ERRORS:
            raise
        except SmbNotFoundError:
            logger.info("%s was deleted after the listing", path)
            return None
        except SmbAccessDeniedError:
            # The service account's view of the share defines the scope, for
            # a file as for a folder.
            logger.info("Skipping %s: the service account may not read it", path)
            return None
        except Exception as e:
            logger.exception("Failed to index %s", path)
            return self._failure(path, e)

    def _list_sorted(
        self, folder: str, *, quiet_missing: bool
    ) -> list[SmbEntry] | None:
        """The folder's entries by name. None for a folder outside the
        service account's view: its view of the share defines the scope. With
        ``quiet_missing``, also None for a folder deleted since its parent
        was listed. The path prefix itself must be readable."""
        try:
            entries: list[SmbEntry] = self.ops.list_folder(path=folder)
        except SmbAccessDeniedError:
            if folder == self.path_prefix:
                raise
            logger.info("Skipping %s: the service account may not list it", folder)
            return None
        except SmbNotFoundError:
            if folder == self.path_prefix or not quiet_missing:
                raise
            logger.info("Skipping %s: it was deleted during the walk", folder)
            return None
        return sorted(entries, key=lambda entry: entry.name)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: SmbCheckpoint,
    ) -> CheckpointOutput[SmbCheckpoint]:
        """Lists one folder and indexes up to ``FILES_PER_STEP`` of its files
        that changed in the window. SMB has no recursive listing and no change
        feed, so every run walks the whole tree."""
        checkpoint = checkpoint.model_copy(deep=True)
        window_start = datetime.fromtimestamp(start, tz=timezone.utc)
        window_end = datetime.fromtimestamp(end, tz=timezone.utc)
        if not checkpoint.started:
            for folder_path in self._folders_to(self.path_prefix):
                yield self._folder_node(folder_path)
            checkpoint.pending = [
                SmbPendingFolder(
                    path=self.path_prefix,
                    last_write_time=self.ops.stat(
                        path=self.path_prefix
                    ).last_write_time,
                )
            ]
            checkpoint.started = True
        if checkpoint.current is None:
            if not checkpoint.pending:
                checkpoint.has_more = False
                return checkpoint
            checkpoint.current = checkpoint.pending.pop()
            checkpoint.last_name = None
        folder: SmbPendingFolder = checkpoint.current

        files_read: int = 0
        for entry in self._list_sorted(folder.path, quiet_missing=True) or []:
            if checkpoint.last_name is not None and entry.name <= checkpoint.last_name:
                continue
            path: str = join_path(folder.path, entry.name)
            if self._is_skipped(entry, path):
                continue
            if entry.is_directory:
                yield self._folder_node(path)
                checkpoint.pending.append(
                    SmbPendingFolder(
                        path=path,
                        last_write_time=entry.last_write_time,
                        index_all=folder.index_all
                        or moved_since(entry, folder.last_write_time, window_start),
                    )
                )
                checkpoint.last_name = entry.name
                continue
            in_window: bool = window_start <= entry.changed_at <= window_end
            if not (folder.index_all or in_window) or not self._is_indexable(entry):
                continue
            if (item := self._index_file(path, entry)) is not None:
                yield item
            checkpoint.last_name = entry.name
            files_read += 1
            if files_read >= FILES_PER_STEP:
                checkpoint.has_more = True
                return checkpoint

        checkpoint.current = None
        checkpoint.last_name = None
        checkpoint.has_more = bool(checkpoint.pending)
        return checkpoint

    def build_dummy_checkpoint(self) -> SmbCheckpoint:
        return SmbCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> SmbCheckpoint:
        return SmbCheckpoint.model_validate_json(checkpoint_json)

    def _with_access(
        self,
        walker: SmbAccessWalker | None,
        items: list[tuple[str, SlimDocument | HierarchyNode]],
    ) -> list[SlimDocument | HierarchyNode]:
        """The items, each with who may read its path when there is a walker.
        Every item gets access then: one without it would keep its old
        access."""
        if walker is None:
            return [item for _, item in items]
        access: dict[str, ExternalAccess] = walker.paths_access(
            [path for path, _ in items]
        )
        for path, item in items:
            item.external_access = access[path]
        return [item for _, item in items]

    def _slim_walk(
        self,
        walker: SmbAccessWalker | None,
        progress_label: str,
        callback: IndexingHeartbeatInterface | None,
    ) -> GenerateSlimDocumentOutput:
        """Every folder and indexable file in scope, parents first. With a
        walker, each with who may read the file or list the folder."""
        # Pruning keeps only the hierarchy nodes a full listing yields.
        yield self._with_access(
            walker,
            [
                (folder_path, self._folder_node(folder_path))
                for folder_path in self._folders_to(self.path_prefix)
            ],
        )
        pending: list[str] = [self.path_prefix]
        while pending:
            # A partial walk would read as deleted files, so stopping raises.
            if callback is not None and callback.should_stop():
                raise RuntimeError(f"{progress_label}: stop signal detected")
            folder: str = pending.pop()
            # Any failure but a refused listing raises: a folder left out by
            # mistake would lose its documents to pruning.
            entries: list[SmbEntry] | None = self._list_sorted(
                folder, quiet_missing=False
            )
            items: list[tuple[str, SlimDocument | HierarchyNode]] = []
            for entry in entries or []:
                path: str = join_path(folder, entry.name)
                if self._is_skipped(entry, path):
                    continue
                if entry.is_directory:
                    items.append((path, self._folder_node(path)))
                    pending.append(path)
                elif self._is_indexable(entry):
                    items.append(
                        (
                            path,
                            SlimDocument(
                                id=self.document_id(path),
                                parent_hierarchy_raw_node_id=self.document_id(folder),
                            ),
                        )
                    )
            for start in range(0, len(items), SLIM_BATCH_SIZE):
                if callback is not None and callback.should_stop():
                    raise RuntimeError(f"{progress_label}: stop signal detected")
                yield self._with_access(walker, items[start : start + SLIM_BATCH_SIZE])
            if callback is not None:
                callback.progress(progress_label, len(items))

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._slim_walk(None, "smb_slim_docs", callback)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every file in scope with who may read it, and every folder with who
        may list it. The doc sync makes any indexed file this does not list
        private, so the window is ignored."""
        walker: SmbAccessWalker | None = build_access_walker(
            self.ops, self.email_attribute
        )
        if walker is None:
            raise RuntimeError(
                "Windows file share permission sync needs Enterprise Edition."
            )
        yield from self._slim_walk(walker, "smb_perm_sync", callback)

    def _path_in_scope(self, document_id: str) -> str | None:
        """The path of a document of this share and path prefix."""
        prefix: str = f"{self._root_id()}/"
        if not document_id.startswith(prefix):
            return None
        path: str = document_id.removeprefix(prefix)
        if self.path_prefix and not path.casefold().startswith(
            f"{self.path_prefix.casefold()}/"
        ):
            return None
        if self._is_excluded(path):
            return None
        return path or None

    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,  # noqa: ARG002
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        """Reads each failed file again, with its folders."""
        for error in errors:
            failed: DocumentFailure | None = error.failed_document
            if failed is None:
                logger.debug(
                    "Skipping a failure with no document: %s", error.failure_message
                )
                continue
            path: str | None = self._path_in_scope(failed.document_id)
            if path is None:
                yield ConnectorFailure(
                    failed_document=failed,
                    failure_message=(
                        f"{failed.document_id} is not a file of this connector's "
                        "share and path prefix."
                    ),
                )
                continue
            try:
                entry: SmbEntry = self.ops.stat(path=path)
            except SmbNotFoundError:
                logger.info("%s no longer exists", path)
                continue
            if self._is_skipped(entry, path) or not self._is_indexable(entry):
                continue
            for folder_path in self._folders_to(parent_path(path)):
                yield self._folder_node(folder_path)
            if (item := self._index_file(path, entry)) is not None:
                yield item
