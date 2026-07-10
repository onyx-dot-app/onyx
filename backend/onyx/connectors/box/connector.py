from collections.abc import Generator
from copy import deepcopy
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

from box_sdk_gen import BoxCCGAuth
from box_sdk_gen import BoxClient
from box_sdk_gen import CCGConfig
from box_sdk_gen.box.errors import BoxAPIError
from box_sdk_gen.schemas.collaboration import Collaboration
from box_sdk_gen.schemas.collaboration import CollaborationStatusField
from box_sdk_gen.schemas.file_full import FileFull
from box_sdk_gen.schemas.folder_mini import FolderMini
from box_sdk_gen.schemas.group_mini import GroupMini
from box_sdk_gen.schemas.user_collaborations import UserCollaborations
from box_sdk_gen.schemas.user_mini import UserMini
from box_sdk_gen.schemas.web_link import WebLink

from onyx.configs.app_configs import BOX_CONNECTOR_SIZE_THRESHOLD
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.box.models import BoxAccessContext
from onyx.connectors.box.models import BoxConnectorCheckpoint
from onyx.connectors.box.models import BoxFolderFrontierEntry
from onyx.connectors.cross_connector_utils.miscellaneous_utils import datetime_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import NormalizationResult
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import get_file_ext
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
_BOX_COLLABORATIONS_PAGE_SIZE = 1000
_SLIM_BATCH_SIZE = 500

_FILE_DOCUMENT_ID_PREFIX = "box-file-"
_WEB_LINK_DOCUMENT_ID_PREFIX = "box-weblink-"

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

# Every Box collaboration role except "uploader" can read/preview content;
# "uploader" is upload-only. Pinned as an allowlist so an unrecognized role
# fails closed.
_READ_ACCESS_COLLABORATION_ROLES = {
    "editor",
    "viewer",
    "previewer",
    "previewer uploader",
    "viewer uploader",
    "co-owner",
    "owner",
}

BOX_GROUP_ID_PREFIX = "box-group"
BOX_ALL_ENTERPRISE_USERS_GROUP_PREFIX = "box-enterprise-all-users"


def box_group_id(group_id: str) -> str:
    return f"{BOX_GROUP_ID_PREFIX}-{group_id}"


def box_all_enterprise_users_group_id(enterprise_id: str) -> str:
    # Scoped by enterprise so two Box connectors on one tenant can't leak
    # "company"-link docs across enterprises via a shared group id.
    return f"{BOX_ALL_ENTERPRISE_USERS_GROUP_PREFIX}-{enterprise_id}"


def box_file_document_id(file_id: str) -> str:
    return f"{_FILE_DOCUMENT_ID_PREFIX}{file_id}"


def box_web_link_document_id(web_link_id: str) -> str:
    return f"{_WEB_LINK_DOCUMENT_ID_PREFIX}{web_link_id}"


def box_file_link(file_id: str) -> str:
    return f"{BOX_APP_BASE_URL}/file/{file_id}"


def parse_box_folder_id(folder_id_or_url: str) -> str:
    """Accepts a raw Box folder ID or a Box folder URL like
    https://app.box.com/folder/123456789 and returns the folder ID."""
    value = folder_id_or_url.strip()
    if not value.startswith(("http://", "https://")):
        return value

    parsed = urlparse(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    # Box uses both /folder/<id> and /folders/<id> in its URLs.
    if len(path_parts) >= 2 and path_parts[-2] in ("folder", "folders"):
        return path_parts[-1]
    raise ConnectorValidationError(
        f"Could not extract a folder ID from Box URL: {folder_id_or_url}"
    )


def normalize_box_login(login: str) -> str:
    """Box logins are emails; lowercase them so stored ACLs match Onyx's
    lowercased user identities (access filters compare emails exactly)."""
    return login.strip().lower()


def _box_api_status_code(error: BoxAPIError) -> int | None:
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


def _collaboration_grants_read(collaboration: Collaboration) -> bool:
    if collaboration.status != CollaborationStatusField.ACCEPTED:
        return False
    if collaboration.role is None:
        return False
    role_value = str(collaboration.role.value)
    if role_value not in _READ_ACCESS_COLLABORATION_ROLES:
        if role_value != "uploader":
            logger.warning("Unrecognized Box collaboration role: %s", role_value)
        return False
    return True


def apply_collaborations_to_access(
    access: BoxAccessContext,
    collaborations: list[Collaboration],
) -> BoxAccessContext:
    """Fold a list of Box collaborations into an access context. Only accepted
    collaborations with a read-capable role grant access."""
    user_emails = set(access.user_emails)
    group_ids = set(access.group_ids)
    for collaboration in collaborations:
        if not _collaboration_grants_read(collaboration):
            continue
        accessible_by = collaboration.accessible_by
        if isinstance(accessible_by, UserCollaborations):
            if accessible_by.login:
                user_emails.add(normalize_box_login(accessible_by.login))
        elif isinstance(accessible_by, GroupMini):
            group_ids.add(box_group_id(accessible_by.id))
    return BoxAccessContext(
        user_emails=user_emails,
        group_ids=group_ids,
        is_public=access.is_public,
    )


def shared_link_access_level(shared_link: Any) -> str | None:
    """Prefer `effective_access` over raw `access`: enterprise policy can
    downgrade an "open" link, and only `effective_access` reflects that (so we
    don't treat a restricted link as public)."""
    if shared_link is None:
        return None
    if shared_link.effective_access is not None:
        return shared_link.effective_access.value
    return shared_link.access.value if shared_link.access else None


def apply_shared_link_to_access(
    access: BoxAccessContext,
    shared_link_access: str | None,
    is_password_enabled: bool | None,
    enterprise_users_group_id: str,
) -> BoxAccessContext:
    """Fold a Box shared link into an access context.

    - "open" links are world-readable -> public (unless password protected).
    - "company" links are readable by any logged-in enterprise user -> the
      (enterprise-scoped) synthetic all-users group, populated by group sync.
    - "collaborators" links grant nothing beyond existing collaborations.
    """
    if shared_link_access is None:
        return access
    if shared_link_access == "open" and not is_password_enabled:
        return access.merged_with(BoxAccessContext(is_public=True))
    if shared_link_access == "company":
        return access.merged_with(
            BoxAccessContext(group_ids={enterprise_users_group_id})
        )
    return access


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

        self._client: BoxClient | None = None
        self._enterprise_client: BoxClient | None = None
        self._enterprise_id: str | None = None

    def set_allow_images(self, value: bool) -> None:
        self.allow_images = value

    @property
    def client(self) -> BoxClient:
        """Client used for content reads. Uses the impersonated user when
        box_user_email is configured, else the app's service account."""
        if self._client is None:
            raise ConnectorMissingCredentialError("Box")
        return self._client

    @property
    def enterprise_client(self) -> BoxClient:
        """Enterprise-subject (service account) client, used for admin-scoped
        APIs like group and user enumeration."""
        if self._enterprise_client is None:
            raise ConnectorMissingCredentialError("Box")
        return self._enterprise_client

    def _all_enterprise_users_group_id(self) -> str:
        if self._enterprise_id is None:
            raise ConnectorMissingCredentialError("Box")
        return box_all_enterprise_users_group_id(self._enterprise_id)

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        client_id = credentials.get("box_client_id")
        client_secret = credentials.get("box_client_secret")
        enterprise_id = credentials.get("box_enterprise_id")
        if not client_id or not client_secret or not enterprise_id:
            raise ConnectorMissingCredentialError("Box")

        auth = BoxCCGAuth(
            config=CCGConfig(
                client_id=client_id,
                client_secret=client_secret,
                enterprise_id=enterprise_id,
            )
        )
        self._enterprise_client = BoxClient(auth=auth)
        self._enterprise_id = enterprise_id

        user_email = credentials.get("box_user_email")
        if user_email:
            user_id = self._resolve_user_id_from_email(user_email)
            self._client = BoxClient(auth=auth.with_user_subject(user_id))
        else:
            self._client = self._enterprise_client
        return None

    def _resolve_user_id_from_email(self, email: str) -> str:
        """Look up the numeric Box user ID for an email so admins configure the
        connector with an email instead of an opaque ID. Requires the app's
        'Manage users' scope (the enterprise-subject client)."""
        normalized = normalize_box_login(email)
        try:
            users = self.enterprise_client.users.get_users(
                filter_term=normalized, fields=["login"], limit=100
            )
        except BoxAPIError as e:
            if _box_api_status_code(e) == 403:
                raise InsufficientPermissionsError(
                    "The Box app cannot look up users by email. Impersonation "
                    "requires the 'Manage users' application scope; enable it and "
                    "reauthorize the app in the Box Admin Console."
                )
            raise
        for user in users.entries or []:
            if user.login and normalize_box_login(user.login) == normalized:
                return user.id
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

    def _fetch_collaborations_access(
        self,
        base_access: BoxAccessContext,
        item_id: str,
        is_folder: bool,
    ) -> BoxAccessContext:
        manager = self.client.list_collaborations
        fetch = (
            manager.get_folder_collaborations
            if is_folder
            else manager.get_file_collaborations
        )
        access = base_access
        marker: str | None = None
        while True:
            collaborations = fetch(
                item_id, limit=_BOX_COLLABORATIONS_PAGE_SIZE, marker=marker
            )
            access = apply_collaborations_to_access(
                access, collaborations.entries or []
            )
            marker = collaborations.next_marker
            if not marker:
                break
        return access

    def _apply_owner(
        self, access: BoxAccessContext, owned_by: UserMini | None
    ) -> BoxAccessContext:
        if owned_by is None or not owned_by.login:
            return access
        return access.merged_with(
            BoxAccessContext(user_emails={normalize_box_login(owned_by.login)})
        )

    def _apply_shared_link(
        self, access: BoxAccessContext, shared_link: Any
    ) -> BoxAccessContext:
        # folder/file/web-link shared links are distinct SDK types that all
        # expose access / effective_access / is_password_enabled.
        if shared_link is None:
            return access
        return apply_shared_link_to_access(
            access,
            shared_link_access_level(shared_link),
            shared_link.is_password_enabled,
            self._all_enterprise_users_group_id(),
        )

    def _resolve_folder_access(
        self,
        folder_id: str,
        inherited_access: BoxAccessContext,
    ) -> BoxAccessContext:
        """Access to a folder's subtree: inherited ancestor access plus the
        folder's own collaborations, shared link, and owner."""
        access = inherited_access
        # Box's root folder (id 0) can't be collaborated; asking for its
        # collaborations returns HTTP 400, so skip that call for root.
        if folder_id != BOX_ROOT_FOLDER_ID:
            access = self._fetch_collaborations_access(
                access, folder_id, is_folder=True
            )
        folder = self.client.folders.get_folder_by_id(
            folder_id, fields=["shared_link", "owned_by"]
        )
        access = self._apply_owner(access, folder.owned_by)
        return self._apply_shared_link(access, folder.shared_link)

    def _resolve_ancestor_access(
        self, path_entries: list[FolderMini] | None
    ) -> BoxAccessContext:
        """Union of collaborations/shared links on a chain of ancestor folders
        (a Box path_collection). Ancestors the credential can't read are
        skipped. Root is excluded."""
        access = BoxAccessContext()
        for ancestor in path_entries or []:
            if ancestor.id == BOX_ROOT_FOLDER_ID:
                continue
            try:
                access = self._resolve_folder_access(ancestor.id, access)
            except BoxAPIError as e:
                status = _box_api_status_code(e)
                if status not in (403, 404):
                    # Fail loud: swallowing a transient error would under-
                    # permission every descendant of this ancestor.
                    raise
                # 403/404 just means the user can't see an ancestor above the
                # configured root; skip it.
                logger.warning(
                    "Cannot read ancestor folder %s while resolving inherited "
                    "access (status=%s); skipping it.",
                    ancestor.id,
                    status,
                )
        return access

    def _resolve_file_access(
        self,
        file: FileFull,
        folder_access: BoxAccessContext,
    ) -> BoxAccessContext:
        access = self._apply_owner(folder_access, file.owned_by)
        if file.has_collaborations:
            access = self._fetch_collaborations_access(access, file.id, is_folder=False)
        return self._apply_shared_link(access, file.shared_link)

    def _resolve_web_link_access(
        self,
        web_link: WebLink,
        folder_access: BoxAccessContext,
    ) -> BoxAccessContext:
        # A bookmark's access is the inherited folder access plus its own shared
        # link (no owner or collaborations). Shared with the full and slim paths
        # so perm sync can't revoke link-granted access.
        return self._apply_shared_link(folder_access, web_link.shared_link)

    def _seed_frontier(self, include_permissions: bool) -> list[BoxFolderFrontierEntry]:
        frontier: list[BoxFolderFrontierEntry] = []
        for folder_id in self.entry_folder_ids:
            folder = self.client.folders.get_folder_by_id(
                folder_id, fields=["name", "path_collection"]
            )
            access: BoxAccessContext | None = None
            if include_permissions:
                access = self._resolve_ancestor_access(
                    folder.path_collection.entries if folder.path_collection else None
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
        stream = self.client.downloads.download_file(file_id=file.id)
        if stream is None:
            return None
        try:
            return stream.read()
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
        if extension in OnyxFileExtensions.IMAGE_EXTENSIONS:
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
                    file_id=f"{box_file_document_id(file.id)}-img-{index}",
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
                external_access = self._resolve_file_access(
                    file, folder.access
                ).to_external_access()

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
            external_access = self._resolve_web_link_access(
                web_link, folder.access
            ).to_external_access()

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
                external_access = self._resolve_file_access(
                    item, folder.access
                ).to_external_access()
            else:
                external_access = self._resolve_web_link_access(
                    item, folder.access
                ).to_external_access()
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

    def _folder_hierarchy_node(self, folder: BoxFolderFrontierEntry) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=folder.folder_id,
            raw_parent_id=folder.parent_folder_id,
            display_name=folder.display_name,
            link=f"{BOX_APP_BASE_URL}/folder/{folder.folder_id}",
            node_type=HierarchyNodeType.FOLDER,
            external_access=(
                folder.access.to_external_access() if folder.access else None
            ),
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
        """Advances the BFS crawl by one unit: seed the frontier on the first
        cycle, start the next folder, or read one page of the current folder's
        items."""
        checkpoint = deepcopy(checkpoint)

        if checkpoint.todo is None:
            checkpoint.todo = self._seed_frontier(include_permissions)
            checkpoint.has_more = True
            return checkpoint

        if checkpoint.current is None:
            if not checkpoint.todo:
                checkpoint.has_more = False
                return checkpoint
            entry = checkpoint.todo.pop(0)
            if entry.folder_id in checkpoint.seen_folder_ids:
                # Already processed via another (overlapping) root; skip so it
                # isn't indexed twice.
                checkpoint.has_more = bool(checkpoint.todo)
                return checkpoint
            checkpoint.seen_folder_ids.add(entry.folder_id)
            if include_permissions:
                try:
                    entry.access = self._resolve_folder_access(
                        entry.folder_id, entry.access or BoxAccessContext()
                    )
                except BoxAPIError as e:
                    yield ConnectorFailure(
                        failed_entity=EntityFailure(entity_id=entry.folder_id),
                        failure_message=(
                            f"Failed to resolve access for Box folder "
                            f"{entry.folder_id} (status={_box_api_status_code(e)}): {e.message}"
                        ),
                        exception=e,
                    )
                    checkpoint.has_more = bool(checkpoint.todo)
                    return checkpoint
            yield self._folder_hierarchy_node(entry)
            checkpoint.current = entry
            checkpoint.current_marker = None
            checkpoint.has_more = True
            return checkpoint

        entry = checkpoint.current
        try:
            items = self.client.folders.get_folder_items(
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
                    f"(status={_box_api_status_code(e)}): {e.message}"
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
        """Group sync enumerates enterprise groups and users, which requires
        the app's 'Manage groups' / 'Manage users' scopes."""
        try:
            self.enterprise_client.groups.get_groups(limit=1)
            self.enterprise_client.users.get_users(limit=1)
        except BoxAPIError as e:
            if _box_api_status_code(e) == 403:
                raise InsufficientPermissionsError(
                    "The Box app cannot enumerate groups/users. Permission sync "
                    "requires the 'Manage groups' and 'Manage users' application "
                    "scopes; enable them and reauthorize the app in the Box "
                    "Admin Console."
                )
            raise

    def validate_connector_settings(self) -> None:
        if self._client is None:
            raise ConnectorMissingCredentialError("Box")

        # Identity check in its own block so its failure reports a credential
        # problem, not the folder-not-found message below.
        try:
            self.client.users.get_user_me()
        except BoxAPIError as e:
            status = _box_api_status_code(e)
            if status in (401, 404):
                raise CredentialExpiredError(
                    "Box credentials are invalid, or the impersonated user could "
                    f"not be authenticated (HTTP {status}). Verify the client "
                    "ID/secret, that the app is authorized in the Box Admin "
                    "Console, and that the impersonated user exists."
                )
            if status == 403:
                raise InsufficientPermissionsError(
                    "The Box app lacks the scopes needed to authenticate (HTTP 403)."
                )
            raise UnexpectedValidationError(
                f"Unexpected Box API error during validation (status={status}): "
                f"{e.message}"
            )

        try:
            for folder_id in self.entry_folder_ids:
                self.client.folders.get_folder_by_id(folder_id, fields=["id"])
        except BoxAPIError as e:
            status = _box_api_status_code(e)
            if status == 403:
                raise InsufficientPermissionsError(
                    "The Box app lacks permission to read a configured folder "
                    "(HTTP 403)."
                )
            if status == 404:
                raise ConnectorValidationError(
                    "A configured Box folder was not found or is not visible to "
                    "the authenticated user (HTTP 404). If using the service "
                    "account (no impersonated user), it must be added as a "
                    "collaborator on the folder."
                )
            raise UnexpectedValidationError(
                f"Unexpected Box API error during validation (status={status}): "
                f"{e.message}"
            )


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
            "box_client_id": environ["BOX_CLIENT_ID"],
            "box_client_secret": environ["BOX_CLIENT_SECRET"],
            "box_enterprise_id": environ["BOX_ENTERPRISE_ID"],
            "box_user_email": environ.get("BOX_USER_EMAIL"),
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
