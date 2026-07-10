from collections import deque
from collections.abc import Generator
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

from box_sdk_gen import BoxCCGAuth, BoxClient, CCGConfig
from box_sdk_gen.box.errors import BoxAPIError
from box_sdk_gen.managers.events import GetEventsEventType, GetEventsStreamType
from box_sdk_gen.schemas.file import File
from box_sdk_gen.schemas.file_full import FileFull
from box_sdk_gen.schemas.folder_mini import FolderMini
from box_sdk_gen.schemas.user_full import UserFull
from box_sdk_gen.schemas.web_link import WebLink

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import BOX_CONNECTOR_SIZE_THRESHOLD, INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.box.access import (
    resolve_box_ancestor_access,
    resolve_box_file_access,
    resolve_box_folder_access,
    resolve_box_web_link_access,
)
from onyx.connectors.box.models import (
    BoxConnectorCheckpoint,
    BoxFolderFrontierEntry,
    BoxTraversalMode,
)
from onyx.connectors.cross_connector_utils.miscellaneous_utils import datetime_to_utc
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    NormalizationResult,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TextSection,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import extract_text_and_images, get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

BOX_ROOT_FOLDER_ID = "0"
BOX_APP_BASE_URL = "https://app.box.com"

# Items per Box folder-items page; also the checkpoint granularity (one page
# of one folder is processed per load_from_checkpoint call).
_BOX_PAGE_SIZE = 200
_SLIM_BATCH_SIZE = 500
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
_MAX_PAGINATION_ITERATIONS = 10_000

_FILE_DOCUMENT_ID_PREFIX = "box-file"
_WEB_LINK_DOCUMENT_ID_PREFIX = "box-weblink"

# Fields requested on folder-items listings. Extra fields that don't apply to
# an entry type are ignored by the API.
_ITEM_FIELDS = [
    "type",
    "id",
    "name",
    "size",
    "modified_at",
    "created_at",
    "owned_by",
    "shared_link",
    "has_collaborations",
    "url",
    "description",
]

# Fields needed to convert a single file fetched via the events path, including
# the parent chain (path_collection) for hierarchy + inherited permissions.
_FILE_FETCH_FIELDS = _ITEM_FIELDS + ["parent", "path_collection"]

# --- Incremental (events) tuning ---
_BOX_EVENTS_PAGE_SIZE = 500
# Poll windows at or below this use the enterprise events stream; wider windows
# (first index, long gaps) fall back to a full crawl. This threshold doubles as
# the reconciliation cadence: a connector idle longer than this re-crawls fully.
_EVENTS_MAX_WINDOW_SECONDS = 7 * 24 * 60 * 60  # 7 days

# Box event types that mean a file's content, name, location, or existence
# changed and it should be re-fetched + re-indexed. Deletes/trashes are handled
# by the slim-based pruning job, so they're intentionally excluded here.
_CONTENT_CHANGE_EVENT_TYPES = [
    GetEventsEventType.UPLOAD,
    GetEventsEventType.EDIT,
    GetEventsEventType.COPY,
    GetEventsEventType.MOVE,
    GetEventsEventType.RENAME,
    GetEventsEventType.UNDELETE,
]
BOX_GROUP_ID_PREFIX = "box-group"
BOX_ALL_ENTERPRISE_USERS_GROUP_PREFIX = "box-enterprise-all-users"

BOX_CLIENT_ID_CREDENTIAL_KEY = "box_client_id"
BOX_CLIENT_SECRET_CREDENTIAL_KEY = "box_client_secret"
BOX_ENTERPRISE_ID_CREDENTIAL_KEY = "box_enterprise_id"
BOX_USER_EMAIL_CREDENTIAL_KEY = "box_user_email"


def box_group_id(group_id: str) -> str:
    return f"{BOX_GROUP_ID_PREFIX}-{group_id}"


def box_all_enterprise_users_group_id(enterprise_id: str) -> str:
    # Scoped by enterprise so two Box connectors on one tenant can't leak
    # "company"-link docs across enterprises via a shared group id.
    return f"{BOX_ALL_ENTERPRISE_USERS_GROUP_PREFIX}-{enterprise_id}"


def box_file_document_id(file_id: str) -> str:
    return f"{_FILE_DOCUMENT_ID_PREFIX}-{file_id}"


def box_web_link_document_id(web_link_id: str) -> str:
    return f"{_WEB_LINK_DOCUMENT_ID_PREFIX}-{web_link_id}"


def box_file_image_id(file_id: str, image_index: int) -> str:
    return f"{box_file_document_id(file_id)}-img-{image_index}"


def box_file_link(file_id: str) -> str:
    return f"{BOX_APP_BASE_URL}/file/{file_id}"


def parse_box_folder_id(folder_id_or_url: str) -> str:
    """Return a validated numeric Box folder ID from an ID or folder URL."""
    value = folder_id_or_url.strip()
    folder_id = value
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        if hostname != "box.com" and not hostname.endswith(".box.com"):
            raise ConnectorValidationError(f"Not a Box folder URL: {folder_id_or_url}")
        path_parts = [part for part in parsed.path.split("/") if part]
        # Box uses both /folder/<id> and /folders/<id> in its URLs.
        if len(path_parts) < 2 or path_parts[-2] not in ("folder", "folders"):
            raise ConnectorValidationError(
                f"Could not extract a folder ID from Box URL: {folder_id_or_url}"
            )
        folder_id = path_parts[-1]

    if not folder_id.isdigit():
        raise ConnectorValidationError(
            f"Box folder ID must contain only digits: {folder_id_or_url}"
        )
    return folder_id


def normalize_box_login(login: str) -> str:
    """Box logins are emails; lowercase them so stored ACLs match Onyx's
    lowercased user identities (access filters compare emails exactly)."""
    return login.strip().lower()


def box_api_status_code(error: BoxAPIError) -> int | None:
    if error.response_info is None:
        return None
    return error.response_info.status_code


def _to_utc(dt: datetime | None) -> datetime | None:
    return datetime_to_utc(dt) if dt is not None else None


def _in_time_window(
    modified_at: datetime | None,
    start: SecondsSinceUnixEpoch | None,
    end: SecondsSinceUnixEpoch | None,
) -> bool:
    if modified_at is None:
        # Items without a modification time can never be excluded safely.
        return True
    timestamp = modified_at.timestamp()
    if start is not None and timestamp < start:
        return False
    if end is not None and timestamp > end:
        return False
    return True


def iter_box_enterprise_users(
    client: BoxClient, filter_term: str | None = None
) -> Generator[UserFull, None, None]:
    marker: str | None = None
    for _ in range(_MAX_PAGINATION_ITERATIONS):
        users = client.users.get_users(
            filter_term=filter_term,
            fields=["login"],
            limit=1000,
            usemarker=True,
            marker=marker,
        )
        yield from users.entries or []
        marker = users.next_marker
        if not marker:
            return
    raise RuntimeError("Box enterprise-user pagination did not terminate")


def _required_string_credential(credentials: dict[str, Any], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value:
        raise ConnectorMissingCredentialError("Box")
    return value


class BoxConnector(
    SlimConnector,
    SlimConnectorWithPermSync,
    CheckpointedConnectorWithPermSync[BoxConnectorCheckpoint],
):
    def __init__(
        self,
        folder_ids: list[str] | None = None,
        include_web_links: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.entry_folder_ids = [
            parse_box_folder_id(folder_id) for folder_id in (folder_ids or [])
        ] or [BOX_ROOT_FOLDER_ID]
        self.include_web_links = include_web_links
        self.batch_size = batch_size
        self.allow_images = False
        self.size_threshold = BOX_CONNECTOR_SIZE_THRESHOLD

        self._content_client: BoxClient | None = None
        self._enterprise_client: BoxClient | None = None
        self._auth: BoxCCGAuth | None = None
        self._enterprise_id: str | None = None
        self._user_email: str | None = None

    def set_allow_images(self, value: bool) -> None:
        self.allow_images = value

    @property
    def content_client(self) -> BoxClient:
        """Client used for content reads. Uses the impersonated user when
        box_user_email is configured, else the app's service account."""
        if self._content_client is None:
            if self._auth is None:
                raise ConnectorMissingCredentialError("Box")
            if self._user_email:
                user_id = self._resolve_user_id_from_email(self._user_email)
                self._content_client = BoxClient(
                    auth=self._auth.with_user_subject(user_id)
                )
            else:
                self._content_client = self.enterprise_client
        return self._content_client

    @property
    def enterprise_client(self) -> BoxClient:
        """Enterprise-subject (service account) client, used for admin-scoped
        APIs like group and user enumeration."""
        if self._enterprise_client is None:
            if self._auth is None:
                raise ConnectorMissingCredentialError("Box")
            self._enterprise_client = BoxClient(auth=self._auth)
        return self._enterprise_client

    @property
    def enterprise_id(self) -> str:
        if self._enterprise_id is None:
            raise ConnectorMissingCredentialError("Box")
        return self._enterprise_id

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        client_id = _required_string_credential(
            credentials, BOX_CLIENT_ID_CREDENTIAL_KEY
        )
        client_secret = _required_string_credential(
            credentials, BOX_CLIENT_SECRET_CREDENTIAL_KEY
        )
        enterprise_id = _required_string_credential(
            credentials, BOX_ENTERPRISE_ID_CREDENTIAL_KEY
        )

        self._auth = BoxCCGAuth(
            config=CCGConfig(
                client_id=client_id,
                client_secret=client_secret,
                enterprise_id=enterprise_id,
            )
        )
        self._enterprise_id = enterprise_id
        user_email = credentials.get(BOX_USER_EMAIL_CREDENTIAL_KEY)
        if user_email is not None and not isinstance(user_email, str):
            raise ConnectorMissingCredentialError("Box")
        self._user_email = user_email or None
        self._enterprise_client = None
        self._content_client = None
        return None

    def _resolve_user_id_from_email(self, email: str) -> str:
        """Look up the numeric Box user ID for an email so admins configure the
        connector with an email instead of an opaque ID. Requires the app's
        'Manage users' scope (the enterprise-subject client)."""
        normalized = normalize_box_login(email)
        try:
            for user in iter_box_enterprise_users(
                self.enterprise_client, filter_term=normalized
            ):
                if user.login and normalize_box_login(user.login) == normalized:
                    return user.id
        except BoxAPIError as error:
            if box_api_status_code(error) == 403:
                raise InsufficientPermissionsError(
                    "The Box app cannot look up users by email. Impersonation "
                    "requires the 'Manage users' application scope; enable it and "
                    "reauthorize the app in the Box Admin Console."
                ) from error
            raise
        raise ConnectorValidationError(
            f"No Box user found with email '{email}'. Enter the email of a user "
            "in this Box enterprise for the connector to impersonate."
        )

    @classmethod
    def normalize_url(cls, url: str) -> NormalizationResult:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        is_box_domain = hostname == "box.com" or hostname.endswith(".box.com")
        if not is_box_domain:
            return NormalizationResult(normalized_url=None, use_default=False)

        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[-2] == "file":
            return NormalizationResult(
                normalized_url=box_file_document_id(path_parts[-1]),
                use_default=False,
            )
        return NormalizationResult(normalized_url=None, use_default=False)

    def _seed_frontier(self, include_permissions: bool) -> list[BoxFolderFrontierEntry]:
        frontier: list[BoxFolderFrontierEntry] = []
        for folder_id in self.entry_folder_ids:
            folder = self.content_client.folders.get_folder_by_id(
                folder_id, fields=["name", "path_collection"]
            )
            access: ExternalAccess | None = None
            if include_permissions:
                access = resolve_box_ancestor_access(
                    self.content_client,
                    folder.path_collection.entries if folder.path_collection else None,
                    self.enterprise_id,
                )
            display_name = folder.name or folder_id
            frontier.append(
                BoxFolderFrontierEntry(
                    folder_id=folder_id,
                    display_name=display_name,
                    parent_folder_id=None,
                    path=display_name,
                    access=access,
                )
            )
        return frontier

    def _download_file(self, file: FileFull) -> bytes | None:
        stream = self.content_client.downloads.download_file(file_id=file.id)
        if stream is None:
            return None
        try:
            chunks: list[bytes] = []
            bytes_read = 0
            while chunk := stream.read(_DOWNLOAD_CHUNK_SIZE):
                bytes_read += len(chunk)
                if bytes_read > self.size_threshold:
                    logger.warning(
                        "Skipping %s: downloaded content exceeds threshold %s",
                        file.name or file.id,
                        self.size_threshold,
                    )
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            stream.close()

    def _file_is_indexable(self, file: FileFull) -> bool:
        """Network-free check of whether a file can yield a document (size + type).
        Used by both the full and slim paths so pruning never keeps a document
        alive for a file the full path would skip."""
        file_name = file.name or file.id
        if file.size is not None and file.size > self.size_threshold:
            logger.warning(
                "Skipping %s: size %s exceeds threshold %s",
                file_name,
                file.size,
                self.size_threshold,
            )
            return False
        extension = get_file_ext(file_name)
        if extension in OnyxFileExtensions.IMAGE_EXTENSIONS and self.allow_images:
            return self.allow_images
        if extension not in OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS:
            logger.debug("Skipping %s: unsupported extension %s", file_name, extension)
            return False
        return True

    def _build_file_sections(
        self, file: FileFull
    ) -> list[TextSection | ImageSection] | None:
        """Returns None when the file should be skipped (unsupported type,
        over the size threshold, images disabled, or empty download)."""
        if not self._file_is_indexable(file):
            return None

        file_name = file.name or file.id
        extension = get_file_ext(file_name)
        link = box_file_link(file.id)

        if extension in OnyxFileExtensions.IMAGE_EXTENSIONS:
            content = self._download_file(file)
            if not content:
                return None
            image_section, _ = store_image_and_create_section(
                image_data=content,
                file_id=box_file_document_id(file.id),
                display_name=file_name,
                link=link,
                file_origin=FileOrigin.CONNECTOR,
            )
            return [image_section]

        content = self._download_file(file)
        if content is None:
            return None

        extraction = extract_text_and_images(BytesIO(content), file_name=file_name)
        sections: list[TextSection | ImageSection] = [
            TextSection(link=link, text=extraction.text_content)
        ]
        if self.allow_images:
            for index, (image_data, image_name) in enumerate(
                extraction.embedded_images
            ):
                image_section, _ = store_image_and_create_section(
                    image_data=image_data,
                    file_id=box_file_image_id(file.id, index),
                    display_name=image_name or f"{file_name} - image {index}",
                    file_origin=FileOrigin.CONNECTOR,
                )
                sections.append(image_section)
        return sections

    def _convert_file(
        self,
        file: FileFull,
        folder: BoxFolderFrontierEntry,
        include_permissions: bool,
    ) -> Document | ConnectorFailure | None:
        document_id = box_file_document_id(file.id)
        try:
            sections = self._build_file_sections(file)
            if sections is None:
                return None

            external_access = None
            if include_permissions and folder.access is not None:
                external_access = resolve_box_file_access(
                    self.content_client, file, folder.access, self.enterprise_id
                )

            primary_owners = None
            if file.owned_by is not None:
                primary_owners = [
                    BasicExpertInfo(
                        display_name=file.owned_by.name,
                        email=file.owned_by.login,
                    )
                ]

            return Document(
                id=document_id,
                sections=sections,
                source=DocumentSource.BOX,
                semantic_identifier=file.name or file.id,
                metadata={"path": folder.path},
                doc_updated_at=_to_utc(file.modified_at),
                doc_created_at=_to_utc(file.created_at),
                primary_owners=primary_owners,
                external_access=external_access,
                parent_hierarchy_raw_node_id=folder.folder_id,
            )
        except Exception as e:
            logger.warning("Failed to process Box file %s: %s", file.id, e)
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=document_id,
                    document_link=box_file_link(file.id),
                ),
                failure_message=f"Failed to process Box file {file.id}: {e}",
                exception=e,
            )

    def _convert_web_link(
        self,
        web_link: WebLink,
        folder: BoxFolderFrontierEntry,
        include_permissions: bool,
    ) -> Document | None:
        if web_link.url is None:
            return None
        name = web_link.name or web_link.url
        text = f"{name}\n{web_link.description}" if web_link.description else name

        external_access = None
        if include_permissions and folder.access is not None:
            external_access = resolve_box_web_link_access(
                web_link, folder.access, self.enterprise_id
            )

        return Document(
            id=box_web_link_document_id(web_link.id),
            sections=[TextSection(link=web_link.url, text=text)],
            source=DocumentSource.BOX,
            semantic_identifier=name,
            metadata={"path": folder.path, "url": web_link.url},
            doc_updated_at=_to_utc(web_link.modified_at),
            doc_created_at=_to_utc(web_link.created_at),
            external_access=external_access,
            parent_hierarchy_raw_node_id=folder.folder_id,
        )

    def _build_slim_document(
        self,
        item: FileFull | WebLink,
        folder: BoxFolderFrontierEntry,
        include_permissions: bool,
    ) -> SlimDocument:
        external_access = None
        if include_permissions and folder.access is not None:
            if isinstance(item, FileFull):
                external_access = resolve_box_file_access(
                    self.content_client, item, folder.access, self.enterprise_id
                )
            else:
                external_access = resolve_box_web_link_access(
                    item, folder.access, self.enterprise_id
                )
        document_id = (
            box_file_document_id(item.id)
            if isinstance(item, FileFull)
            else box_web_link_document_id(item.id)
        )
        return SlimDocument(
            id=document_id,
            external_access=external_access,
            parent_hierarchy_raw_node_id=folder.folder_id,
        )

    def _pick_current_from_todos(
        self,
        checkpoint: BoxConnectorCheckpoint,
        include_permissions: bool,
    ) -> Generator[
        HierarchyNode | ConnectorFailure,
        None,
        BoxConnectorCheckpoint,
    ]:
        if not checkpoint.todo:
            checkpoint.has_more = False
            return checkpoint

        todo = deque(checkpoint.todo)
        entry = todo.popleft()
        checkpoint.todo = list(todo)
        if entry.folder_id in checkpoint.seen_folder_ids:
            checkpoint.has_more = bool(checkpoint.todo)
            return checkpoint

        checkpoint.seen_folder_ids.add(entry.folder_id)
        if include_permissions:
            try:
                entry.access = resolve_box_folder_access(
                    self.content_client,
                    entry.folder_id,
                    entry.access,
                    self.enterprise_id,
                )
            except BoxAPIError as error:
                yield ConnectorFailure(
                    failed_entity=EntityFailure(entity_id=entry.folder_id),
                    failure_message=(
                        f"Failed to resolve access for Box folder "
                        f"{entry.folder_id} (status={box_api_status_code(error)}): "
                        f"{error.message}"
                    ),
                    exception=error,
                )
                checkpoint.has_more = bool(checkpoint.todo)
                return checkpoint

        yield self._folder_hierarchy_node(entry)
        checkpoint.current = entry
        checkpoint.current_marker = None
        checkpoint.has_more = True
        return checkpoint

    def _folder_hierarchy_node(self, entry: BoxFolderFrontierEntry) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=entry.folder_id,
            raw_parent_id=entry.parent_folder_id,
            display_name=entry.display_name,
            link=f"{BOX_APP_BASE_URL}/folder/{entry.folder_id}",
            node_type=HierarchyNodeType.FOLDER,
            external_access=entry.access,
        )

    def _load_one_page(
        self,
        checkpoint: BoxConnectorCheckpoint,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        include_permissions: bool,
        slim: bool,
    ) -> Generator[
        Document | SlimDocument | HierarchyNode | ConnectorFailure,
        None,
        BoxConnectorCheckpoint,
    ]:
        """Advances the traversal by one unit. On the first cycle it picks a
        mode (FULL crawl vs incremental EVENTS) and seeds it; thereafter it
        dispatches one page of work to the chosen mode."""
        checkpoint = deepcopy(checkpoint)

        if checkpoint.mode is None:
            # Use the incremental events stream only for a steady-state,
            # short-window poll of a whole-enterprise connector. Everything else
            # crawls the tree: slim (pruning / perm-sync must enumerate the
            # whole corpus), folder-scoped connectors (events can't scope to a
            # subtree), and the first index / long gaps (window > the
            # reconciliation cadence) which also serve as a full reconciliation.
            window = end - start if start is not None and end is not None else None
            use_events = (
                not slim
                and self.entry_folder_ids == [BOX_ROOT_FOLDER_ID]
                and window is not None
                and 0 < window <= _EVENTS_MAX_WINDOW_SECONDS
            )
            checkpoint.mode = (
                BoxTraversalMode.EVENTS if use_events else BoxTraversalMode.FULL
            )
            if checkpoint.mode == BoxTraversalMode.FULL:
                checkpoint.todo = self._seed_frontier(include_permissions)
            checkpoint.has_more = True
            return checkpoint

        if checkpoint.mode == BoxTraversalMode.EVENTS:
            if start is None or end is None:
                # EVENTS is only selected for a bounded window (see the decision
                # above); if that ever fails to hold, fall back to a full crawl.
                checkpoint.mode = BoxTraversalMode.FULL
                checkpoint.todo = self._seed_frontier(include_permissions)
                checkpoint.has_more = True
                return checkpoint
            new_checkpoint = yield from self._advance_events(
                checkpoint, start, end, include_permissions
            )
            return new_checkpoint

        new_checkpoint = yield from self._advance_full(
            checkpoint, start, end, include_permissions, slim
        )
        return new_checkpoint

    def _advance_full(
        self,
        checkpoint: BoxConnectorCheckpoint,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        include_permissions: bool,
        slim: bool,
    ) -> Generator[
        Document | SlimDocument | HierarchyNode | ConnectorFailure,
        None,
        BoxConnectorCheckpoint,
    ]:
        """One unit of the BFS crawl: start the next folder, or read one page
        of the current folder's items."""
        if checkpoint.current is None:
            return (
                yield from self._pick_current_from_todos(
                    checkpoint, include_permissions
                )
            )

        entry = checkpoint.current
        try:
            items = self.content_client.folders.get_folder_items(
                entry.folder_id,
                fields=_ITEM_FIELDS,
                usemarker=True,
                marker=checkpoint.current_marker,
                limit=_BOX_PAGE_SIZE,
            )
        except BoxAPIError as e:
            yield ConnectorFailure(
                failed_entity=EntityFailure(entity_id=entry.folder_id),
                failure_message=(
                    f"Failed to list Box folder {entry.folder_id} "
                    f"(status={box_api_status_code(e)}): {e.message}"
                ),
                exception=e,
            )
            checkpoint.current = None
            checkpoint.current_marker = None
            checkpoint.has_more = bool(checkpoint.todo)
            return checkpoint

        for item in items.entries or []:
            if isinstance(item, FolderMini):
                child_name = item.name or item.id
                checkpoint.todo.append(
                    BoxFolderFrontierEntry(
                        folder_id=item.id,
                        display_name=child_name,
                        parent_folder_id=entry.folder_id,
                        path=f"{entry.path}/{child_name}",
                        access=entry.access,
                    )
                )
            elif isinstance(item, FileFull):
                if not _in_time_window(item.modified_at, start, end):
                    continue
                if slim:
                    # Mirror the full path's skip criteria (see _file_is_indexable).
                    if not self._file_is_indexable(item):
                        continue
                    yield self._build_slim_document(item, entry, include_permissions)
                else:
                    converted = self._convert_file(item, entry, include_permissions)
                    if converted is not None:
                        yield converted
            elif isinstance(item, WebLink):
                if not self.include_web_links:
                    continue
                if not _in_time_window(item.modified_at, start, end):
                    continue
                if slim:
                    yield self._build_slim_document(item, entry, include_permissions)
                else:
                    web_link_doc = self._convert_web_link(
                        item, entry, include_permissions
                    )
                    if web_link_doc is not None:
                        yield web_link_doc

        if items.next_marker:
            checkpoint.current_marker = items.next_marker
        else:
            checkpoint.current = None
            checkpoint.current_marker = None
        checkpoint.has_more = checkpoint.current is not None or bool(checkpoint.todo)
        return checkpoint

    def _folder_entry_for_file(
        self, file: FileFull, include_permissions: bool
    ) -> BoxFolderFrontierEntry | None:
        """Build the parent-folder frontier entry for a file discovered via the
        events stream (no BFS context available). Resolves the folder's full
        inherited access from the file's path_collection when perm-syncing."""
        if file.parent is None:
            return None
        path_entries = (
            file.path_collection.entries if file.path_collection else None
        ) or []
        # path_collection is root..immediate-parent; the grandparent is the
        # entry just before the immediate parent.
        non_root = [e for e in path_entries if e.id != BOX_ROOT_FOLDER_ID]
        grandparent_id = non_root[-2].id if len(non_root) >= 2 else None
        path = "/".join(e.name or e.id for e in non_root) or (
            file.parent.name or file.parent.id
        )
        access = (
            resolve_box_ancestor_access(
                self.content_client, path_entries, self.enterprise_id
            )
            if include_permissions
            else None
        )
        return BoxFolderFrontierEntry(
            folder_id=file.parent.id,
            display_name=file.parent.name or file.parent.id,
            parent_folder_id=grandparent_id,
            path=path,
            access=access,
        )

    def _advance_events(
        self,
        checkpoint: BoxConnectorCheckpoint,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        include_permissions: bool,
    ) -> Generator[
        Document | HierarchyNode | ConnectorFailure, None, BoxConnectorCheckpoint
    ]:
        """One page of the enterprise events stream: fetch changed files and
        yield their re-indexed documents (+ parent folder nodes). Deletes are
        left to the slim-based pruning job."""
        # The framework already overlaps successive poll windows by
        # POLL_CONNECTOR_OFFSET (30 min), which covers Box's normal admin_logs
        # ingestion lag, so `start` needs no extra buffer here.
        created_after = datetime.fromtimestamp(start, tz=timezone.utc)
        created_before = datetime.fromtimestamp(end, tz=timezone.utc)
        try:
            events = self.enterprise_client.events.get_events(
                stream_type=GetEventsStreamType.ADMIN_LOGS,
                event_type=_CONTENT_CHANGE_EVENT_TYPES,
                created_after=created_after,
                created_before=created_before,
                stream_position=checkpoint.event_stream_position,
                limit=_BOX_EVENTS_PAGE_SIZE,
            )
        except BoxAPIError as e:
            # Events need the admin/enterprise scope and can hit transient
            # issues. Rather than silently index nothing, fall back to a full
            # crawl for this run (mirrors SharePoint's 410 -> full-resync).
            logger.warning(
                "Box events fetch failed (status=%s); falling back to a full "
                "crawl for this run.",
                box_api_status_code(e),
            )
            checkpoint.mode = BoxTraversalMode.FULL
            checkpoint.todo = self._seed_frontier(include_permissions)
            checkpoint.event_stream_position = None
            checkpoint.has_more = True
            return checkpoint

        entries = events.entries or []
        for event in entries:
            source = event.source
            if not isinstance(source, File):
                continue  # only file content changes; folder/user events ignored
            file_id = source.id
            if file_id in checkpoint.event_seen_file_ids:
                continue
            checkpoint.event_seen_file_ids.add(file_id)

            try:
                file = self.content_client.files.get_file_by_id(
                    file_id, fields=_FILE_FETCH_FIELDS
                )
            except BoxAPIError as e:
                status = box_api_status_code(e)
                if status in (403, 404):
                    # Not visible to the indexing user, or already gone; a
                    # deletion is reconciled by pruning.
                    continue
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=box_file_document_id(file_id),
                        document_link=box_file_link(file_id),
                    ),
                    failure_message=(
                        f"Failed to fetch changed Box file {file_id} "
                        f"(status={status}): {e.message}"
                    ),
                    exception=e,
                )
                continue

            entry = self._folder_entry_for_file(file, include_permissions)
            if entry is None:
                continue
            if entry.folder_id not in checkpoint.seen_folder_ids:
                checkpoint.seen_folder_ids.add(entry.folder_id)
                yield self._folder_hierarchy_node(entry)
            converted = self._convert_file(file, entry, include_permissions)
            if converted is not None:
                yield converted

        next_position = events.next_stream_position
        next_str = str(next_position) if next_position is not None else None
        if (
            not entries
            or next_str is None
            or next_str == checkpoint.event_stream_position
        ):
            checkpoint.has_more = False
        else:
            checkpoint.event_stream_position = next_str
            checkpoint.has_more = True
        return checkpoint

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: BoxConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[BoxConnectorCheckpoint]:
        page_generator = self._load_one_page(
            checkpoint, start, end, include_permissions, slim=False
        )
        while True:
            try:
                item = next(page_generator)
            except StopIteration as e:
                return e.value
            if isinstance(item, SlimDocument):
                raise RuntimeError("Unexpected SlimDocument in full document load")
            yield item

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: BoxConnectorCheckpoint,
    ) -> CheckpointOutput[BoxConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=False
        )

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: BoxConnectorCheckpoint,
    ) -> CheckpointOutput[BoxConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=True
        )

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
            page_generator = self._load_one_page(
                checkpoint, start, end, include_permissions, slim=True
            )
            while True:
                try:
                    item = next(page_generator)
                except StopIteration as e:
                    checkpoint = e.value
                    break
                if isinstance(item, ConnectorFailure):
                    # Slim retrieval feeds permission sync and pruning; silently
                    # dropping a subtree could revoke or leak access, so fail loudly.
                    raise RuntimeError(
                        f"Box slim retrieval failed: {item.failure_message}"
                    ) from item.exception
                if isinstance(item, (SlimDocument, HierarchyNode)):
                    batch.append(item)
                    if len(batch) >= _SLIM_BATCH_SIZE:
                        yield batch
                        batch = []
            if callback:
                if callback.should_stop():
                    raise RuntimeError("Box slim retrieval: stop signal detected")
                callback.progress("box_slim_retrieval", 1)
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

    def build_dummy_checkpoint(self) -> BoxConnectorCheckpoint:
        return BoxConnectorCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> BoxConnectorCheckpoint:
        return BoxConnectorCheckpoint.model_validate_json(checkpoint_json)

    def probe_group_listing_permission(self) -> None:
        """Verify the scopes required by Box permission group sync."""
        try:
            self.enterprise_client.groups.get_groups(limit=1)
            self.enterprise_client.users.get_users(limit=1)
        except BoxAPIError as error:
            if box_api_status_code(error) == 403:
                raise InsufficientPermissionsError(
                    "The Box app cannot enumerate groups/users. Permission sync "
                    "requires the 'Manage groups' and 'Manage users' application "
                    "scopes; enable them and reauthorize the app in the Box "
                    "Admin Console."
                ) from error
            raise

    def validate_connector_settings(self) -> None:
        if self._auth is None:
            raise ConnectorMissingCredentialError("Box")

        # Identity check in its own block so its failure reports a credential
        # problem, not the folder-not-found message below.
        try:
            self.content_client.users.get_user_me()
        except BoxAPIError as e:
            status = box_api_status_code(e)
            if status in (401, 404):
                raise CredentialExpiredError(
                    "Box credentials are invalid, or the impersonated user could "
                    f"not be authenticated (HTTP {status}). Verify the client "
                    "ID/secret, that the app is authorized in the Box Admin "
                    "Console, and that the impersonated user exists."
                ) from e
            if status == 403:
                raise InsufficientPermissionsError(
                    "The Box app lacks the scopes needed to authenticate (HTTP 403)."
                ) from e
            raise UnexpectedValidationError(
                f"Unexpected Box API error during validation (status={status}): "
                f"{e.message}"
            ) from e

        try:
            for folder_id in self.entry_folder_ids:
                self.content_client.folders.get_folder_by_id(folder_id, fields=["id"])
        except BoxAPIError as e:
            status = box_api_status_code(e)
            if status == 403:
                raise InsufficientPermissionsError(
                    "The Box app lacks permission to read a configured folder "
                    "(HTTP 403)."
                ) from e
            if status == 404:
                raise ConnectorValidationError(
                    "A configured Box folder was not found or is not visible to "
                    "the authenticated user (HTTP 404). If using the service "
                    "account (no impersonated user), it must be added as a "
                    "collaborator on the folder."
                ) from e
            raise UnexpectedValidationError(
                f"Unexpected Box API error during validation (status={status}): "
                f"{e.message}"
            ) from e


if __name__ == "__main__":
    from os import environ
    from time import time

    from onyx.connectors.connector_runner import ConnectorRunner

    connector = BoxConnector(
        folder_ids=(
            environ["BOX_FOLDER_IDS"].split(",")
            if environ.get("BOX_FOLDER_IDS")
            else None
        ),
    )
    connector.load_credentials(
        {
            BOX_CLIENT_ID_CREDENTIAL_KEY: environ["BOX_CLIENT_ID"],
            BOX_CLIENT_SECRET_CREDENTIAL_KEY: environ["BOX_CLIENT_SECRET"],
            BOX_ENTERPRISE_ID_CREDENTIAL_KEY: environ["BOX_ENTERPRISE_ID"],
            BOX_USER_EMAIL_CREDENTIAL_KEY: environ.get("BOX_USER_EMAIL"),
        }
    )

    start_time = datetime.fromtimestamp(0, tz=timezone.utc)
    end_time = datetime.fromtimestamp(time(), tz=timezone.utc)
    runner: ConnectorRunner[BoxConnectorCheckpoint] = ConnectorRunner(
        connector,
        batch_size=10,
        include_permissions=False,
        time_range=(start_time, end_time),
    )

    current_checkpoint = connector.build_dummy_checkpoint()
    while current_checkpoint.has_more:
        for document_batch, hierarchy_batch, failure, next_checkpoint in runner.run(
            current_checkpoint
        ):
            if document_batch:
                for document in document_batch:
                    print(f"doc: {document.to_short_descriptor()}")
            if hierarchy_batch:
                for node in hierarchy_batch:
                    print(f"folder: {node.raw_node_id} ({node.display_name})")
            if failure:
                print(f"failure: {failure.failure_message}")
            if next_checkpoint:
                current_checkpoint = next_checkpoint
