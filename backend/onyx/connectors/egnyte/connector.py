from collections.abc import Generator
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.parse import quote

from pydantic import Field

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.app_configs import (
    EGNYTE_CLIENT_ID,
    EGNYTE_CLIENT_SECRET,
    INDEX_BATCH_SIZE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
)
from onyx.connectors.egnyte.access import (
    EgnyteUnknownGroupError,
    get_folder_access,
    load_directory,
)
from onyx.connectors.egnyte.models import (
    EgnyteDirectory,
    EgnyteFile,
    EgnyteFolder,
    EgnyteFolderPage,
)
from onyx.connectors.egnyte.source_operations import (
    EgnyteApiError,
    EgnyteSourceOperations,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    OAuthConnector,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import (
    detect_encoding,
    extract_file_text,
    get_file_ext,
    read_text_file,
)
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries

logger = setup_logger()

_DOCUMENT_ID_PREFIX = "egnyte-"
# Entries per folder listing page, and the checkpoint unit: one page of one
# folder per load_from_checkpoint call.
FOLDER_PAGE_SIZE = 200
# Each page re-reads the last tenth of the previous one, which absorbs that
# many deletions between two requests without skipping a live entry.
_PAGE_OVERLAP = FOLDER_PAGE_SIZE // 10
_SLIM_BATCH_SIZE = 500
# Egnyte refuses to list the permissions of these folders. They hold only
# folders, and only administrators read them.
_PATHS_WITHOUT_PERMISSIONS = frozenset({"/", "/private"})
OAUTH_SCOPES = "Egnyte.filesystem Egnyte.permission Egnyte.user Egnyte.group"


def egnyte_document_id(group_id: str) -> str:
    """group_id stays the same across file versions, unlike entry_id."""
    return f"{_DOCUMENT_ID_PREFIX}{group_id}"


def parse_egnyte_document_id(document_id: str) -> str | None:
    """The file's group_id, or None for an id the walk does not make."""
    group_id = document_id.removeprefix(_DOCUMENT_ID_PREFIX)
    if group_id == document_id or not group_id:
        return None
    return group_id


def same_path(left: str, right: str) -> bool:
    """Egnyte paths are case-insensitive."""
    return left.lower() == right.lower()


def lists_permissions(folder_path: str) -> bool:
    return folder_path.lower() not in _PATHS_WITHOUT_PERMISSIONS


def normalize_folder_path(folder_path: str | None) -> str:
    """Egnyte paths start with "/", so "Shared/Docs" names "/Shared/Docs"."""
    return "/" + (folder_path or "").strip("/")


def _is_under(path: str, folder_path: str) -> bool:
    return folder_path == "/" or path.lower().startswith(folder_path.lower() + "/")


def _app_base(domain: str) -> str:
    return f"https://{domain}.egnyte.com"


def _parse_last_modified(last_modified: str) -> datetime:
    return datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z").replace(
        tzinfo=timezone.utc
    )


def _in_time_window(
    file: EgnyteFile,
    start: SecondsSinceUnixEpoch | None,
    end: SecondsSinceUnixEpoch | None,
) -> bool:
    timestamp = _parse_last_modified(file.last_modified).timestamp()
    if start is not None and timestamp < start:
        return False
    if end is not None and timestamp > end:
        return False
    return True


def is_indexable(file: EgnyteFile) -> bool:
    """Shared by indexing and the slim listing, so pruning never keeps a
    document for a file indexing skips."""
    # TODO(wenxi-onyx): consider allowing images
    return get_file_ext(file.name) in OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS


def _extract_text(file: EgnyteFile, file_content: BytesIO) -> str:
    if get_file_ext(file.name) in OnyxFileExtensions.PLAIN_TEXT_EXTENSIONS:
        text, _ = read_text_file(
            file_content,
            encoding=detect_encoding(file_content),
            ignore_onyx_metadata=False,
        )
        return text
    return extract_file_text(
        file=file_content, file_name=file.name, break_on_unprocessable=True
    )


def _build_document(
    file: EgnyteFile, text: str, base_url: str, parent_folder_id: str
) -> Document:
    metadata: dict[str, str | list[str]] = {
        "file_path": file.path,
        "last_modified": file.last_modified,
    }
    if file.lock_info:
        metadata["lock_owner"] = (
            f"{file.lock_info.first_name} {file.lock_info.last_name}"
        )
    return Document(
        id=egnyte_document_id(file.group_id),
        sections=[
            TextSection(
                text=text.strip(), link=f"{base_url}/navigate/file/{file.group_id}"
            )
        ],
        source=DocumentSource.EGNYTE,
        semantic_identifier=file.name,
        metadata=metadata,
        doc_updated_at=_parse_last_modified(file.last_modified),
        # Egnyte gives a username, the closest it has to an email.
        primary_owners=(
            [BasicExpertInfo(email=file.uploaded_by)] if file.uploaded_by else None
        ),
        parent_hierarchy_raw_node_id=parent_folder_id,
    )


def _prefixed(access: ExternalAccess) -> ExternalAccess:
    """Doc sync adds the source prefix to group ids when it stores them.
    Indexing and hierarchy nodes store access as given, so they carry it."""
    return ExternalAccess(
        external_user_emails=access.external_user_emails,
        external_user_group_ids={
            build_ext_group_name_for_onyx(group_id, DocumentSource.EGNYTE)
            for group_id in access.external_user_group_ids
        },
        is_public=access.is_public,
    )


def _is_fatal(error: Exception) -> bool:
    """A rejected token, a used-up daily quota or an unreachable Egnyte fails
    every later call too, so it ends the run instead of failing one item. The
    checkpoint resumes the walk."""
    return isinstance(error, (CredentialInvalidError, UnexpectedValidationError))


def _reindex_failure(
    target: DocumentFailure, message: str, exception: Exception | None = None
) -> ConnectorFailure:
    """Keeps the target's link, so the error row still points at the file."""
    return ConnectorFailure(
        failed_document=target, failure_message=message, exception=exception
    )


class EgnyteCheckpoint(ConnectorCheckpoint):
    # Folder paths left to walk, breadth first. None until the walk starts.
    todo: list[str] | None = None
    # The folder being paged and the offset of its next page.
    current_path: str | None = None
    offset: int = 0
    # Entry paths of the page before, so the overlap is not yielded twice.
    previous_page_paths: list[str] = Field(default_factory=list)
    # The current folder's readers with bare group ids, read with its first
    # page. None outside permission sync runs.
    current_access: ExternalAccess | None = None


class EgnyteConnector(
    CheckpointedConnectorWithPermSync[EgnyteCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
    OAuthConnector,
    Resolver,
):
    supports_manual_credentials = True
    slim_listing_honors_indexing_start = True

    class AdditionalOauthKwargs(OAuthConnector.AdditionalOauthKwargs):
        egnyte_domain: str = Field(
            title="Egnyte Domain",
            description=(
                "The domain for the Egnyte instance (e.g. 'company' for company.egnyte.com)"
            ),
        )

    def __init__(
        self,
        folder_path: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.domain = ""  # will always be set in `load_credentials`
        self.folder_path = normalize_folder_path(folder_path)
        self.batch_size = batch_size
        self._ops: EgnyteSourceOperations | None = None
        self._directory: EgnyteDirectory | None = None

    @property
    def ops(self) -> EgnyteSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("Egnyte")
        return self._ops

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.EGNYTE

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,
        state: str,
        additional_kwargs: dict[str, str],
        code_challenge: str | None = None,  # noqa: ARG003
    ) -> str:
        if not EGNYTE_CLIENT_ID:
            raise ValueError("EGNYTE_CLIENT_ID environment variable must be set")

        oauth_kwargs = cls.AdditionalOauthKwargs(**additional_kwargs)

        callback_uri = get_oauth_callback_uri(base_domain, "egnyte")
        return (
            f"https://{oauth_kwargs.egnyte_domain}.egnyte.com/puboauth/token"
            f"?client_id={EGNYTE_CLIENT_ID}"
            f"&redirect_uri={callback_uri}"
            f"&scope={quote(OAUTH_SCOPES)}"
            f"&state={state}"
            f"&response_type=code"
        )

    @classmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,
        code: str,
        additional_kwargs: dict[str, str],
        code_verifier: str | None = None,  # noqa: ARG003
    ) -> dict[str, Any]:
        if not EGNYTE_CLIENT_ID:
            raise ValueError("EGNYTE_CLIENT_ID environment variable must be set")
        if not EGNYTE_CLIENT_SECRET:
            raise ValueError("EGNYTE_CLIENT_SECRET environment variable must be set")

        oauth_kwargs = cls.AdditionalOauthKwargs(**additional_kwargs)

        # Exchange code for token
        url = f"https://{oauth_kwargs.egnyte_domain}.egnyte.com/puboauth/token"
        redirect_uri = get_oauth_callback_uri(base_domain, "egnyte")

        data = {
            "client_id": EGNYTE_CLIENT_ID,
            "client_secret": EGNYTE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "scope": OAUTH_SCOPES,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = request_with_retries(
            method="POST",
            url=url,
            data=data,
            headers=headers,
            # try a lot faster since this is a realtime flow
            backoff=0,
            delay=0.1,
        )
        if not response.ok:
            raise RuntimeError(f"Failed to exchange code for token: {response.text}")

        token_data = response.json()
        return {
            "domain": oauth_kwargs.egnyte_domain,
            "access_token": token_data["access_token"],
        }

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.domain = credentials["domain"]
        self._ops = EgnyteSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.EGNYTE.value, credentials
            )
        )
        return None

    def validate_connector_settings(self) -> None:
        try:
            self.ops.list_folder_page(
                folder_path=self.folder_path, offset=0, page_size=1
            )
        except EgnyteApiError as e:
            if e.status_code == 404:
                raise ConnectorValidationError(
                    f"Egnyte folder {self.folder_path} was not found."
                ) from e
            raise UnexpectedValidationError(str(e)) from e

    def _folder_access(self, page: EgnyteFolderPage) -> ExternalAccess | None:
        if self._directory is None:
            return None
        return get_folder_access(self.domain, page.permissions, self._directory)

    def _list_page(
        self, path: str, offset: int, with_permissions: bool
    ) -> EgnyteFolderPage:
        # Every page carries the folder's permissions, so they are read once.
        if with_permissions and lists_permissions(path):
            return self.ops.list_folder_page_with_permissions(
                folder_path=path, offset=offset, page_size=FOLDER_PAGE_SIZE
            )
        return self.ops.list_folder_page(
            folder_path=path, offset=offset, page_size=FOLDER_PAGE_SIZE
        )

    def _folder_node(
        self, folder: EgnyteFolder, access: ExternalAccess | None
    ) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=folder.folder_id,
            # The configured folder is the top of this connector's tree.
            raw_parent_id=(
                None if same_path(folder.path, self.folder_path) else folder.parent_id
            ),
            display_name=folder.name or folder.path,
            link=f"{_app_base(self.domain)}/navigate/folder/{folder.folder_id}",
            node_type=HierarchyNodeType.FOLDER,
            external_access=_prefixed(access) if access is not None else None,
        )

    def _convert_file(
        self,
        file: EgnyteFile,
        parent_folder_id: str,
        access: ExternalAccess | None,
    ) -> Document | ConnectorFailure | None:
        document_id = egnyte_document_id(file.group_id)
        try:
            content = self.ops.download_file(group_id=file.group_id)
            document = _build_document(
                file,
                _extract_text(file, content),
                _app_base(self.domain),
                parent_folder_id,
            )
            document.external_access = _prefixed(access) if access else None
            return document
        except Exception as e:
            if _is_fatal(e):
                raise
            if isinstance(e, EgnyteApiError) and e.status_code == 404:
                logger.warning("File '%s' was deleted before download.", file.path)
                return None
            logger.warning("Failed to process Egnyte file %s: %s", file.path, e)
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=document_id,
                    document_link=f"{_app_base(self.domain)}/navigate/file/{file.group_id}",
                ),
                failure_message=f"Failed to process Egnyte file {file.path}: {e}",
                exception=e,
            )

    def _walk_step(
        self,
        checkpoint: EgnyteCheckpoint,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        slim: bool,
        include_permissions: bool,
    ) -> Generator[
        Document | SlimDocument | HierarchyNode | ConnectorFailure,
        None,
        EgnyteCheckpoint,
    ]:
        """Reads one page of one folder. The folder's node comes with its first
        page, and its subfolders join the end of the queue."""
        checkpoint = checkpoint.model_copy(deep=True)
        if checkpoint.todo is None:
            checkpoint.todo = [self.folder_path]
        if checkpoint.current_path is None:
            if not checkpoint.todo:
                checkpoint.has_more = False
                return checkpoint
            checkpoint.current_path = checkpoint.todo.pop(0)
            checkpoint.offset = 0
            checkpoint.previous_page_paths = []
            checkpoint.current_access = None

        if include_permissions and self._directory is None:
            # Outside the per-folder handling: without the directory no folder
            # can get access, so a failure here ends the run.
            self._directory = load_directory(self.ops)

        path = checkpoint.current_path
        # Also read mid-folder, when a checkpoint saved without permissions
        # resumes in a permission run.
        reads_access = (
            include_permissions
            and self._directory is not None
            and checkpoint.current_access is None
        )
        try:
            page: EgnyteFolderPage = self._list_page(
                path, checkpoint.offset, reads_access
            )
            if reads_access:
                checkpoint.current_access = self._folder_access(page)
        except (
            EgnyteApiError,
            InsufficientPermissionsError,
            EgnyteUnknownGroupError,
        ) as e:
            # A partial slim walk reads as deletions, so only indexing goes on.
            if slim:
                raise
            yield ConnectorFailure(
                failed_entity=EntityFailure(entity_id=path),
                failure_message=f"Failed to list Egnyte folder {path}: {e}",
                exception=e,
            )
            checkpoint.current_path = None
            checkpoint.has_more = bool(checkpoint.todo)
            return checkpoint

        access = checkpoint.current_access
        if checkpoint.offset == 0:
            yield self._folder_node(page.folder, access)
        previous = set(checkpoint.previous_page_paths)
        checkpoint.todo.extend(
            folder.path for folder in page.folders if folder.path not in previous
        )
        for file in page.files:
            if file.path in previous:
                continue
            if not is_indexable(file) or not _in_time_window(file, start, end):
                continue
            if slim:
                # Bare group ids: doc sync adds the source prefix when it stores them.
                yield SlimDocument(
                    id=egnyte_document_id(file.group_id),
                    external_access=access,
                    parent_hierarchy_raw_node_id=page.folder.folder_id,
                )
                continue
            converted = self._convert_file(file, page.folder.folder_id, access)
            if converted is not None:
                yield converted

        page_paths = [entry.path for entry in [*page.folders, *page.files]]
        if len(page_paths) < FOLDER_PAGE_SIZE:
            checkpoint.current_path = None
            checkpoint.previous_page_paths = []
        else:
            checkpoint.offset += FOLDER_PAGE_SIZE - _PAGE_OVERLAP
            checkpoint.previous_page_paths = page_paths
        checkpoint.has_more = checkpoint.current_path is not None or bool(
            checkpoint.todo
        )
        return checkpoint

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: EgnyteCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[EgnyteCheckpoint]:
        step = self._walk_step(
            checkpoint, start, end, slim=False, include_permissions=include_permissions
        )
        while True:
            try:
                item = next(step)
            except StopIteration as e:
                return e.value
            if isinstance(item, SlimDocument):
                raise RuntimeError("Unexpected SlimDocument in full document load")
            yield item

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: EgnyteCheckpoint,
    ) -> CheckpointOutput[EgnyteCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=False
        )

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: EgnyteCheckpoint,
    ) -> CheckpointOutput[EgnyteCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=True
        )

    def build_dummy_checkpoint(self) -> EgnyteCheckpoint:
        return EgnyteCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> EgnyteCheckpoint:
        return EgnyteCheckpoint.model_validate_json(checkpoint_json)

    def _retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        callback: IndexingHeartbeatInterface | None,
        include_permissions: bool,
    ) -> GenerateSlimDocumentOutput:
        checkpoint = self.build_dummy_checkpoint()
        batch: list[SlimDocument | HierarchyNode] = []
        while checkpoint.has_more:
            # A partial walk reads as deletions, so stopping raises.
            if callback is not None and callback.should_stop():
                raise RuntimeError("Egnyte slim retrieval: stop signal detected")
            step = self._walk_step(
                checkpoint,
                start,
                end,
                slim=True,
                include_permissions=include_permissions,
            )
            while True:
                try:
                    item = next(step)
                except StopIteration as e:
                    checkpoint = e.value
                    break
                if isinstance(item, (Document, ConnectorFailure)):
                    raise RuntimeError(f"Unexpected {type(item).__name__} in slim walk")
                batch.append(item)
                if len(batch) >= _SLIM_BATCH_SIZE:
                    yield batch
                    batch = []
            if callback is not None:
                callback.progress("egnyte_slim_retrieval", 1)
        if batch:
            yield batch

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        return self._retrieve_all_slim_docs(
            start, end, callback, include_permissions=False
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        return self._retrieve_all_slim_docs(
            start, end, callback, include_permissions=True
        )

    def _ancestor_paths(self, file_path: str) -> list[str]:
        """The folders from the configured folder down to the file's own, in
        Egnyte's own case, which the configured path may not match."""
        top_depth = len([name for name in self.folder_path.split("/") if name])
        parents = [name for name in file_path.split("/") if name][:-1]
        return [
            "/" + "/".join(parents[:depth])
            for depth in range(top_depth, len(parents) + 1)
        ]

    def _reindex_document(
        self,
        target: DocumentFailure,
        include_permissions: bool,
        folders: dict[str, tuple[EgnyteFolder, ExternalAccess | None]],
        yielded_folder_ids: set[str],
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        document_id = target.document_id
        group_id = parse_egnyte_document_id(document_id)
        if group_id is None:
            yield _reindex_failure(
                target, f"'{document_id}' is not an Egnyte document id."
            )
            return
        try:
            file = self.ops.get_file(group_id=group_id)
        except EgnyteApiError as e:
            if e.status_code != 404:
                raise
            # The retry worker reads a missing result as a new failure, so
            # the reason is given. Pruning removes the document.
            yield _reindex_failure(target, f"Egnyte file {document_id} was deleted.", e)
            return
        if not _is_under(file.path, self.folder_path):
            yield _reindex_failure(
                target,
                f"Egnyte file {file.path} is outside {self.folder_path}.",
            )
            return
        if not is_indexable(file):
            yield _reindex_failure(
                target, f"Egnyte file {file.path} is not a supported type."
            )
            return

        chain: list[tuple[EgnyteFolder, ExternalAccess | None]] = []
        for path in self._ancestor_paths(file.path):
            if path not in folders:
                page = self._list_page(path, 0, include_permissions)
                access = self._folder_access(page) if include_permissions else None
                folders[path] = (page.folder, access)
            chain.append(folders[path])
        for folder, access in chain:
            if folder.folder_id not in yielded_folder_ids:
                yielded_folder_ids.add(folder.folder_id)
                yield self._folder_node(folder, access)
        parent, parent_access = chain[-1]
        converted = self._convert_file(file, parent.folder_id, parent_access)
        if converted is not None:
            yield converted

    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        if include_permissions and self._directory is None:
            self._directory = load_directory(self.ops)
        # Folders and their nodes are shared by many failed files.
        folders: dict[str, tuple[EgnyteFolder, ExternalAccess | None]] = {}
        yielded_folder_ids: set[str] = set()
        for failure in errors:
            if failure.failed_document is None:
                continue
            target = failure.failed_document
            try:
                yield from self._reindex_document(
                    target, include_permissions, folders, yielded_folder_ids
                )
            except Exception as e:
                if _is_fatal(e):
                    raise
                yield _reindex_failure(
                    target,
                    f"Failed to read Egnyte file {target.document_id}: {e}",
                    e,
                )
