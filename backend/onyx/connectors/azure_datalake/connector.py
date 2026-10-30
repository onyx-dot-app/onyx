import posixpath
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import BLOB_STORAGE_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.access import (
    AzureDataLakeAccessWalker,
    build_access_walker,
    prefix_azure_datalake_external_groups,
)
from onyx.connectors.azure_datalake.models import (
    AzureDataLakeCheckpoint,
    AzureDataLakePath,
)
from onyx.connectors.azure_datalake.source_operations import (
    CONFIG_ACCOUNT_NAME,
    CONFIG_CONTAINER_NAME,
    AzureDataLakeSourceOperations,
)
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
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError,
    MicrosoftGraphError,
    raise_for_auth_error,
    raise_for_graph_error,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

DOCUMENT_ID_PREFIX = "azure_datalake"
# Paths per checkpoint step. The listing allows up to 5000.
PAGE_SIZE = 1000
# Backstop for a cursor that cycles.
_MAX_PAGES = 1_000_000
BLOB_ENDPOINT_SUFFIX = "blob.core.windows.net"

# Failures that stop the attempt: the credential or the account itself, not
# one file.
_ATTEMPT_ERRORS = (
    CredentialInvalidError,
    UnreachableValidationError,
    MicrosoftAuthError,
    MicrosoftGraphError,
)


def has_indexable_name(path: str, *, allow_images: bool) -> bool:
    ext: str = get_file_ext(posixpath.basename(path))
    if ext not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
        logger.debug("Skipping unsupported file type: %s", path)
        return False
    if ext in OnyxFileExtensions.IMAGE_EXTENSIONS and not allow_images:
        logger.debug("Skipping image file: %s (images are off)", path)
        return False
    return True


def is_indexable_file(
    path: AzureDataLakePath, *, allow_images: bool, size_threshold: int
) -> bool:
    """Indexing, the slim listing and the file-read check admit the same
    files."""
    if path.is_directory or not has_indexable_name(
        path.name, allow_images=allow_images
    ):
        return False
    if path.content_length > size_threshold:
        logger.info(
            "Skipping %s: %s bytes is over the %s byte limit",
            path.name,
            path.content_length,
            size_threshold,
        )
        return False
    return True


class AzureDataLakeConnector(
    CheckpointedConnector[AzureDataLakeCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
    Resolver,
    CredentialsConnector,
):
    def __init__(
        self,
        account_name: str,
        container_name: str,
        path_prefix: str = "",
    ) -> None:
        self.account_name = account_name
        self.container_name = container_name
        self.path_prefix = path_prefix
        self.size_threshold: int = BLOB_STORAGE_SIZE_THRESHOLD
        self._allow_images = False
        self._ops: AzureDataLakeSourceOperations | None = None

    @property
    def ops(self) -> AzureDataLakeSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("Azure Data Lake")
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use set_credentials_provider with this connector.")

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = AzureDataLakeSourceOperations(
            credentials_provider=credentials_provider,
            connector_specific_config={
                CONFIG_ACCOUNT_NAME: self.account_name,
                CONFIG_CONTAINER_NAME: self.container_name,
            },
        )

    def set_allow_images(self, value: bool) -> None:
        self._allow_images = value

    def validate_connector_settings(self) -> None:
        """Reads the first entry under the path prefix: the gateway names a
        rejected credential, a missing container or path, or a missing role."""
        try:
            self.ops.list_paths_page(
                path_prefix=self.path_prefix,
                recursive=False,
                page_size=1,
                continuation_token=None,
            )
        except MicrosoftAuthError as e:
            raise_for_auth_error(e)
        except MicrosoftGraphError as e:
            raise_for_graph_error(
                e, "Microsoft's token endpoint refused the app registration."
            )

    def document_id(self, path: str) -> str:
        """Account and container names repeat across tenants, so both are in
        the id with the path."""
        return f"{DOCUMENT_ID_PREFIX}:{self.account_name}:{self.container_name}:{path}"

    def _container_node_id(self) -> str:
        return f"{DOCUMENT_ID_PREFIX}:{self.account_name}:{self.container_name}"

    def _parent_node_id(self, path: str) -> str:
        parent: str = posixpath.dirname(path)
        return self.document_id(parent) if parent else self._container_node_id()

    def _container_url(self) -> str:
        return (
            f"https://{self.account_name}.{BLOB_ENDPOINT_SUFFIX}/{self.container_name}"
        )

    def _link(self, path: str) -> str:
        return f"{self._container_url()}/{quote(path)}"

    def _container_node(self) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=self._container_node_id(),
            raw_parent_id=None,
            display_name=self.container_name,
            link=self._container_url(),
            node_type=HierarchyNodeType.FOLDER,
        )

    def _directory_node(self, path: str) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=self.document_id(path),
            raw_parent_id=self._parent_node_id(path),
            display_name=posixpath.basename(path),
            link=self._link(path),
            node_type=HierarchyNodeType.FOLDER,
        )

    @staticmethod
    def _ancestor_directories(path: str) -> list[str]:
        """Every directory above ``path``, parents first."""
        parts: list[str] = path.split("/")[:-1] if path else []
        return ["/".join(parts[: depth + 1]) for depth in range(len(parts))]

    def _ancestor_nodes(self, path: str) -> list[HierarchyNode]:
        """The container and every directory above ``path``, parents first."""
        return [
            self._container_node(),
            *(
                self._directory_node(directory)
                for directory in self._ancestor_directories(path)
            ),
        ]

    def _is_indexable(self, path: AzureDataLakePath) -> bool:
        return is_indexable_file(
            path, allow_images=self._allow_images, size_threshold=self.size_threshold
        )

    def _failure(self, path: str, error: Exception) -> ConnectorFailure:
        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=self.document_id(path), document_link=self._link(path)
            ),
            failure_message=f"Failed to index Azure Data Lake file {path}: {error}",
            exception=error,
        )

    def _read_document(self, path: str) -> Document | None:
        """The file as a document. None when it grew past the size limit or
        holds nothing to index."""
        file = self.ops.read_file(path=path, max_bytes=self.size_threshold)
        if file.content is None:
            logger.info("Skipping %s: it grew past the size limit", path)
            return None
        document: Document | None = build_storage_file_document(
            file_bytes=file.content,
            file_name=posixpath.basename(path),
            document_id=self.document_id(path),
            source=DocumentSource.AZURE_DATALAKE,
            link=self._link(path),
            last_modified=file.last_modified,
            image_file_id=quote(self.document_id(path), safe=""),
            raw_file_callback=self.raw_file_callback,
            include_embedded_images=self._allow_images,
        )
        if document is not None:
            document.parent_hierarchy_raw_node_id = self._parent_node_id(path)
        return document

    def _index_file(self, path: str) -> Document | ConnectorFailure | None:
        try:
            return self._read_document(path)
        except _ATTEMPT_ERRORS:
            raise
        except Exception as e:
            logger.exception("Failed to index Azure Data Lake file %s", path)
            return self._failure(path, e)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: AzureDataLakeCheckpoint,
    ) -> CheckpointOutput[AzureDataLakeCheckpoint]:
        """Indexes the files of one listing page that changed in the window.
        The listing has no time filter, so every run walks the whole prefix."""
        checkpoint = checkpoint.model_copy(deep=True)
        if checkpoint.continuation_token is None:
            yield from self._ancestor_nodes(
                f"{self.path_prefix}/" if self.path_prefix else ""
            )
        page = self.ops.list_paths_page(
            path_prefix=self.path_prefix,
            recursive=True,
            page_size=PAGE_SIZE,
            continuation_token=checkpoint.continuation_token,
        )
        window_start = datetime.fromtimestamp(start, tz=timezone.utc)
        window_end = datetime.fromtimestamp(end, tz=timezone.utc)
        for path in page.paths:
            if path.is_directory:
                yield self._directory_node(path.name)
                continue
            if not window_start <= path.last_modified <= window_end:
                continue
            if not self._is_indexable(path):
                continue
            if (item := self._index_file(path.name)) is not None:
                yield item
        checkpoint.continuation_token = page.continuation_token
        checkpoint.has_more = page.continuation_token is not None
        return checkpoint

    def build_dummy_checkpoint(self) -> AzureDataLakeCheckpoint:
        return AzureDataLakeCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> AzureDataLakeCheckpoint:
        return AzureDataLakeCheckpoint.model_validate_json(checkpoint_json)

    def _prefix_nodes(
        self, walker: AzureDataLakeAccessWalker | None
    ) -> list[HierarchyNode]:
        """The container and the path prefix's directories. With a walker,
        each with who may list it."""
        container: HierarchyNode = self._container_node()
        if walker is not None:
            container.external_access = prefix_azure_datalake_external_groups(
                walker.container_access()
            )
        nodes: list[HierarchyNode] = [container]
        for directory in self._ancestor_directories(
            f"{self.path_prefix}/" if self.path_prefix else ""
        ):
            node: HierarchyNode = self._directory_node(directory)
            if walker is not None:
                node.external_access = prefix_azure_datalake_external_groups(
                    walker.directory_access(directory)
                )
            nodes.append(node)
        return nodes

    def _slim_walk(
        self,
        walker: AzureDataLakeAccessWalker | None,
        progress_label: str,
        callback: IndexingHeartbeatInterface | None,
    ) -> GenerateSlimDocumentOutput:
        """Every directory and indexable file in scope, parents first. With a
        walker, each with who may read the file or list the directory."""
        # Pruning keeps only the hierarchy nodes a full listing yields.
        batch: list[SlimDocument | HierarchyNode] = list(self._prefix_nodes(walker))
        continuation_token: str | None = None
        for _ in range(_MAX_PAGES):
            # A partial walk would read as deleted files, so stopping raises.
            if callback is not None and callback.should_stop():
                raise RuntimeError(
                    f"Azure Data Lake {progress_label}: stop signal detected"
                )
            page = self.ops.list_paths_page(
                path_prefix=self.path_prefix,
                recursive=True,
                page_size=PAGE_SIZE,
                continuation_token=continuation_token,
            )
            entries: list[AzureDataLakePath] = [
                path
                for path in page.paths
                if path.is_directory or self._is_indexable(path)
            ]
            access: dict[str, ExternalAccess] = (
                walker.page_access(entries) if walker is not None else {}
            )
            for path in entries:
                # Every entry has access with a walker. A node without it
                # would keep its old access.
                path_access: ExternalAccess | None = (
                    access[path.name] if walker is not None else None
                )
                if path.is_directory:
                    node: HierarchyNode = self._directory_node(path.name)
                    if path_access is not None:
                        node.external_access = prefix_azure_datalake_external_groups(
                            path_access
                        )
                    batch.append(node)
                    continue
                batch.append(
                    SlimDocument(
                        id=self.document_id(path.name),
                        external_access=path_access,
                        parent_hierarchy_raw_node_id=self._parent_node_id(path.name),
                    )
                )
            yield batch
            batch = []
            if callback is not None:
                callback.progress(progress_label, len(entries))
            continuation_token = page.continuation_token
            if continuation_token is None:
                return
        raise RuntimeError(f"Azure Data Lake listing passed {_MAX_PAGES} pages")

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._slim_walk(None, "azure_datalake_slim_docs", callback)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every file in scope with who may read it, and every directory with
        who may list it. The doc sync makes any indexed file this does not
        list private, so the window is ignored."""
        walker: AzureDataLakeAccessWalker | None = build_access_walker(
            self.ops, self.account_name, self.container_name
        )
        if walker is None:
            raise RuntimeError(
                "Azure Data Lake permission sync needs Enterprise Edition."
            )
        yield from self._slim_walk(walker, "azure_datalake_perm_sync", callback)

    def _path_in_scope(self, document_id: str) -> str | None:
        """The path of a document of this account, container and prefix."""
        prefix: str = self.document_id("")
        if not document_id.startswith(prefix):
            return None
        path: str = document_id.removeprefix(prefix)
        if self.path_prefix and not path.startswith(f"{self.path_prefix}/"):
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
                        "container and path prefix."
                    ),
                )
                continue
            if not has_indexable_name(path, allow_images=self._allow_images):
                continue
            yield from self._ancestor_nodes(path)
            if (item := self._index_file(path)) is not None:
                yield item
