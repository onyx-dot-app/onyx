from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.microsoft_utils.drive_delta import (
    DRIVE_DELTA_SELECT_FIELDS,
    DriveDeltaItem,
    build_drive_delta_start_url,
)
from onyx.connectors.microsoft_utils.drive_items import (
    DriveItemContent,
    DriveItemData,
    build_item_relative_path,
    drive_item_in_time_window,
    is_path_excluded,
)
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    resolve_microsoft_environment,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
)
from onyx.connectors.onedrive.access import (
    get_ce_onedrive_access,
    get_onedrive_external_access,
)
from onyx.connectors.onedrive.errors import OneDriveGraphError
from onyx.connectors.onedrive.models import (
    OneDriveCheckpoint,
    OneDriveDrive,
    OneDrivePermission,
    OneDriveSettings,
    OneDriveUser,
)
from onyx.connectors.onedrive.scope import normalize_configured_users
from onyx.connectors.onedrive.source_operations import (
    CONFIG_ALL_USERS,
    CONFIG_AUTHORITY_HOST,
    CONFIG_GRAPH_API_HOST,
    CONFIG_USERS,
    GRAPH_API_VERSION,
    OneDriveSourceOperations,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

ROOT_NODE_SUFFIX = "root"
HIERARCHY_ID_SEPARATOR = ":"
METADATA_DRIVE = "drive"
METADATA_PATH = "path"
USER_UNAVAILABLE_STATUSES = frozenset({403, 404})
MAX_PERMISSION_ENTRIES = ExternalAccess.MAX_NUM_ENTRIES
MAX_CACHED_FOLDER_PERMISSIONS = 1_000


def _last_delta_item_occurrences(
    items: list[DriveDeltaItem],
) -> list[DriveDeltaItem]:
    seen_ids: set[str] = set()
    latest_items: list[DriveDeltaItem] = []
    for item in reversed(items):
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        latest_items.append(item)
    return list(reversed(latest_items))


def _is_user_unavailable(error: OneDriveGraphError) -> bool:
    return error.status in USER_UNAVAILABLE_STATUSES


def _is_transient(error: OneDriveGraphError) -> bool:
    return error.status is None or error.status == 429 or error.status >= 500


def _validate_user_scope(settings: OneDriveSettings) -> None:
    if settings.all_users and settings.users:
        raise ConnectorValidationError(
            "Do not list users when all-user indexing is selected."
        )
    if not settings.all_users and not settings.users:
        raise ConnectorValidationError("Select all users or list at least one user.")


def hierarchy_item_id(drive_id: str, item_id: str) -> str:
    return HIERARCHY_ID_SEPARATOR.join((drive_id, item_id))


def drive_root_id(drive_id: str) -> str:
    return hierarchy_item_id(drive_id, ROOT_NODE_SUFFIX)


def item_parent_id(drive_id: str, item: DriveDeltaItem) -> str:
    parent = item.parent_reference
    if parent is None or not parent.id:
        return drive_root_id(drive_id)
    path = parent.path or ""
    if "root:/" not in path:
        return drive_root_id(drive_id)
    return hierarchy_item_id(drive_id, parent.id)


def user_root_node(
    user: OneDriveUser,
    drive: OneDriveDrive,
    external_access: ExternalAccess | None = None,
) -> HierarchyNode:
    return HierarchyNode(
        raw_node_id=drive_root_id(drive.id),
        raw_parent_id=None,
        display_name=user.display_name or user.user_principal_name,
        link=drive.web_url,
        node_type=HierarchyNodeType.MY_DRIVE,
        external_access=external_access or get_ce_onedrive_access(),
    )


def folder_node(
    drive: OneDriveDrive,
    item: DriveDeltaItem,
    external_access: ExternalAccess | None = None,
) -> HierarchyNode:
    return HierarchyNode(
        raw_node_id=hierarchy_item_id(drive.id, item.id),
        raw_parent_id=item_parent_id(drive.id, item),
        display_name=item.name or "",
        link=item.web_url,
        node_type=HierarchyNodeType.FOLDER,
        external_access=external_access or get_ce_onedrive_access(),
    )


def _owner(item: DriveItemData) -> list[BasicExpertInfo] | None:
    if not item.last_modified_by_display_name and not item.last_modified_by_email:
        return None
    return [
        BasicExpertInfo(
            display_name=item.last_modified_by_display_name,
            email=item.last_modified_by_email,
        )
    ]


def drive_item_document(
    item: DriveItemData,
    drive: OneDriveDrive,
    content: DriveItemContent,
    parent_hierarchy_raw_node_id: str,
    external_access: ExternalAccess | None = None,
) -> Document:
    return Document(
        id=item.id,
        sections=content.sections,
        source=DocumentSource.ONEDRIVE,
        semantic_identifier=item.name,
        title=item.name,
        doc_created_at=item.created_datetime,
        doc_updated_at=item.last_modified_datetime,
        primary_owners=_owner(item),
        metadata={
            METADATA_DRIVE: drive.name,
            METADATA_PATH: build_item_relative_path(
                item.parent_reference_path, item.name
            ),
        },
        external_access=external_access or get_ce_onedrive_access(),
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        file_id=content.staged_file_id,
    )


def _entity_failure(
    user: OneDriveUser | str, message: str, error: Exception | None = None
) -> ConnectorFailure:
    identifier = user.user_principal_name if isinstance(user, OneDriveUser) else user
    return ConnectorFailure(
        failed_entity=EntityFailure(entity_id=identifier),
        failure_message=message,
        exception=error,
    )


def _document_failure(item: DriveItemData, error: Exception) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(
            document_id=item.id, document_link=item.web_url
        ),
        failure_message=f"OneDrive document `{item.name}` failed: {error}",
        exception=error,
    )


class OneDriveConnector(
    SlimConnector,
    SlimConnectorWithPermSync,
    CredentialsConnector,
    CheckpointedConnectorWithPermSync[OneDriveCheckpoint],
):
    def __init__(
        self,
        users: list[str] | None = None,
        all_users: bool = True,
        excluded_paths: list[str] | None = None,
        treat_organization_link_as_public: bool = False,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        normalized_users = normalize_configured_users(users)
        self.settings = OneDriveSettings(
            users=normalized_users,
            all_users=all_users,
            excluded_paths=[
                path.strip() for path in excluded_paths or [] if path.strip()
            ],
            treat_organization_link_as_public=treat_organization_link_as_public,
            authority_host=authority_host.rstrip("/"),
            graph_api_host=graph_api_host.rstrip("/"),
            batch_size=batch_size,
        )
        _validate_user_scope(self.settings)
        resolve_microsoft_environment(
            self.settings.graph_api_host, self.settings.authority_host
        )
        self._ops: OneDriveSourceOperations | None = None
        self._folder_access: dict[str, ExternalAccess] = {}

    @property
    def ops(self) -> OneDriveSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("OneDrive")
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.set_credentials_provider(
            OnyxStaticCredentialsProvider(
                None, DocumentSource.ONEDRIVE.value, credentials
            )
        )
        return None

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = OneDriveSourceOperations(
            credentials_provider=credentials_provider,
            connector_specific_config={
                CONFIG_AUTHORITY_HOST: self.settings.authority_host,
                CONFIG_GRAPH_API_HOST: self.settings.graph_api_host,
                CONFIG_ALL_USERS: self.settings.all_users,
                CONFIG_USERS: self.settings.users,
            },
        )

    def validate_connector_settings(self) -> None:
        resolve_microsoft_environment(
            self.settings.graph_api_host, self.settings.authority_host
        )
        _validate_user_scope(self.settings)

    def build_dummy_checkpoint(self) -> OneDriveCheckpoint:
        return OneDriveCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> OneDriveCheckpoint:
        return OneDriveCheckpoint.model_validate_json(checkpoint_json)

    def _clear_current_user(self, checkpoint: OneDriveCheckpoint) -> None:
        checkpoint.current_user = None
        checkpoint.current_drive = None
        checkpoint.delta_cursor = None
        checkpoint.delta_started = False

    def _finish_drive(self, checkpoint: OneDriveCheckpoint) -> None:
        self._clear_current_user(checkpoint)
        self._folder_access.clear()

    def _list_all_permissions(
        self, drive_id: str, item_id: str
    ) -> list[OneDrivePermission]:
        permissions: list[OneDrivePermission] = []
        next_link: str | None = None
        while True:
            page = self.ops.list_permissions(
                drive_id=drive_id,
                item_id=item_id,
                next_link=next_link,
            )
            permissions.extend(page.permissions)
            if len(permissions) > MAX_PERMISSION_ENTRIES:
                raise ValueError(
                    f"OneDrive item `{item_id}` exceeds the permission entry limit."
                )
            next_link = page.next_link
            if next_link is None:
                return permissions

    def _direct_access(
        self,
        user: OneDriveUser,
        drive: OneDriveDrive,
        item_id: str,
        *,
        add_prefix: bool,
    ) -> ExternalAccess:
        permissions = self._list_all_permissions(drive.id, item_id)
        return get_onedrive_external_access(
            permissions,
            user.user_principal_name,
            self.settings.treat_organization_link_as_public,
            add_prefix=add_prefix,
        )

    def _item_access(
        self,
        user: OneDriveUser,
        drive: OneDriveDrive,
        item: DriveDeltaItem,
        *,
        add_prefix: bool,
    ) -> ExternalAccess:
        parent_id = item.parent_reference.id if item.parent_reference else None
        parent_access = self._folder_access.get(
            hierarchy_item_id(drive.id, parent_id) if parent_id else ""
        )
        if not item.is_folder and item.shared is None and parent_access is not None:
            return parent_access
        access = self._direct_access(user, drive, item.id, add_prefix=add_prefix)
        if item.is_folder:
            cache_key = hierarchy_item_id(drive.id, item.id)
            self._folder_access[cache_key] = access
            if len(self._folder_access) > MAX_CACHED_FOLDER_PERMISSIONS:
                oldest_key = next(iter(self._folder_access))
                del self._folder_access[oldest_key]
        return access

    def _select_explicit_user(
        self, checkpoint: OneDriveCheckpoint
    ) -> Generator[ConnectorFailure, None, None]:
        if checkpoint.configured_user_index >= len(self.settings.users):
            checkpoint.has_more = False
            return
        identifier = self.settings.users[checkpoint.configured_user_index]
        try:
            user = self.ops.get_user(identifier=identifier)
        except OneDriveGraphError as error:
            if not _is_user_unavailable(error):
                raise
            checkpoint.configured_user_index += 1
            yield _entity_failure(identifier, str(error), error)
            return
        checkpoint.configured_user_index += 1
        if user is None:
            yield _entity_failure(identifier, f"No user matches `{identifier}`.")
            return
        checkpoint.current_user = user

    def _select_discovered_user(self, checkpoint: OneDriveCheckpoint) -> None:
        if not checkpoint.user_page:
            if checkpoint.user_listing_started and checkpoint.users_next_link is None:
                checkpoint.has_more = False
                return
            page = self.ops.list_users(next_link=checkpoint.users_next_link)
            checkpoint.user_listing_started = True
            checkpoint.users_next_link = page.next_link
            checkpoint.user_page = page.users
        if checkpoint.user_page:
            checkpoint.current_user = checkpoint.user_page.pop(0)

    def _open_current_drive(
        self, checkpoint: OneDriveCheckpoint
    ) -> Generator[ConnectorFailure, None, None]:
        user = checkpoint.current_user
        if user is None:
            return
        try:
            drive = self.ops.get_default_drive(user_id=user.id)
        except OneDriveGraphError as error:
            if not _is_user_unavailable(error):
                raise
            if not self.settings.all_users:
                yield _entity_failure(user, str(error), error)
            else:
                logger.info(
                    "OneDrive: skipping inaccessible drive for %s (%s)",
                    user.user_principal_name,
                    error.code,
                )
            self._clear_current_user(checkpoint)
            return
        if drive is None:
            if not self.settings.all_users:
                yield _entity_failure(
                    user, f"`{user.user_principal_name}` has no OneDrive."
                )
            else:
                logger.info(
                    "OneDrive: skipping %s without a drive", user.user_principal_name
                )
            self._clear_current_user(checkpoint)
            return
        checkpoint.current_drive = drive

    def _path_allowed(self, item: DriveDeltaItem) -> bool:
        path = build_item_relative_path(
            item.parent_reference.path if item.parent_reference else None,
            item.name or "",
        )
        return not is_path_excluded(path, self.settings.excluded_paths)

    def _item_allowed(
        self,
        item: DriveDeltaItem,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> bool:
        if (
            get_file_ext(item.name or "")
            not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS
        ):
            return False
        graph_json = item.to_graph_json()
        if not drive_item_in_time_window(graph_json, start_at, end_at):
            return False
        return self._path_allowed(item)

    def _file_output(
        self,
        item: DriveDeltaItem,
        drive: OneDriveDrive,
        external_access: ExternalAccess | None = None,
    ) -> Document | ConnectorFailure | None:
        drive_item = DriveItemData.from_graph_json(item.to_graph_json())
        if drive_item.drive_id is None:
            drive_item = drive_item.model_copy(update={"drive_id": drive.id})
        try:
            content = self.ops.download_item(
                item=drive_item, raw_file_callback=self.raw_file_callback
            )
        except Exception as error:
            return _document_failure(drive_item, error)
        if content is None:
            return None
        parent = item_parent_id(drive.id, item)
        return drive_item_document(
            drive_item, drive, content, parent, external_access=external_access
        )

    def _read_delta_page(
        self,
        checkpoint: OneDriveCheckpoint,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        *,
        include_permissions: bool,
    ) -> Generator[Document | HierarchyNode | ConnectorFailure, None, None]:
        user = checkpoint.current_user
        drive = checkpoint.current_drive
        assert user is not None and drive is not None
        start_at = datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        end_at = datetime.fromtimestamp(end, tz=timezone.utc) if end else None
        page_url = checkpoint.delta_cursor or build_drive_delta_start_url(
            f"{self.settings.graph_api_host}/{GRAPH_API_VERSION}",
            drive.id,
            start=start_at,
            page_size=self.settings.batch_size,
            select_fields=DRIVE_DELTA_SELECT_FIELDS,
        )
        try:
            result = self.ops.get_delta_page(
                drive_id=drive.id,
                page_url=page_url,
                page_size=self.settings.batch_size,
            )
        except OneDriveGraphError as error:
            if not _is_user_unavailable(error):
                raise
            if not self.settings.all_users:
                yield _entity_failure(user, str(error), error)
            else:
                logger.info(
                    "OneDrive: skipping inaccessible delta for %s (%s)",
                    user.user_principal_name,
                    error.code,
                )
            self._finish_drive(checkpoint)
            return
        if not checkpoint.delta_started:
            root_access = (
                ExternalAccess(
                    external_user_emails={user.user_principal_name.lower()},
                    external_user_group_ids=set(),
                    is_public=False,
                )
                if include_permissions
                else None
            )
            yield user_root_node(user, drive, root_access)
        checkpoint.delta_started = True
        checkpoint.delta_cursor = result.next_cursor
        if result.resynced:
            return
        for item in _last_delta_item_occurrences(result.page.items):
            if item.is_tombstone:
                continue
            if item.is_folder:
                if not self._path_allowed(item):
                    continue
                try:
                    access = (
                        self._item_access(user, drive, item, add_prefix=True)
                        if include_permissions
                        else None
                    )
                except OneDriveGraphError as error:
                    if _is_transient(error):
                        raise
                    yield _entity_failure(item.id, str(error), error)
                    continue
                except Exception as error:
                    yield _entity_failure(item.id, str(error), error)
                    continue
                yield folder_node(drive, item, access)
                continue
            if not item.is_file or not self._item_allowed(item, None, end_at):
                continue
            try:
                access = (
                    self._item_access(user, drive, item, add_prefix=True)
                    if include_permissions
                    else None
                )
            except Exception as error:
                yield _document_failure(
                    DriveItemData.from_graph_json(item.to_graph_json()), error
                )
                continue
            output = self._file_output(item, drive, access)
            if output is not None:
                yield output
        if result.next_cursor is None:
            self._finish_drive(checkpoint)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: OneDriveCheckpoint,
    ) -> CheckpointOutput[OneDriveCheckpoint]:
        if checkpoint.current_user is None:
            if self.settings.all_users:
                self._select_discovered_user(checkpoint)
            else:
                yield from self._select_explicit_user(checkpoint)
            return checkpoint
        if checkpoint.current_drive is None:
            yield from self._open_current_drive(checkpoint)
            return checkpoint
        yield from self._read_delta_page(
            checkpoint, start, end, include_permissions=False
        )
        return checkpoint

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: OneDriveCheckpoint,
    ) -> CheckpointOutput[OneDriveCheckpoint]:
        if checkpoint.current_user is None:
            if self.settings.users:
                yield from self._select_explicit_user(checkpoint)
            else:
                self._select_discovered_user(checkpoint)
            return checkpoint
        if checkpoint.current_drive is None:
            yield from self._open_current_drive(checkpoint)
            return checkpoint
        yield from self._read_delta_page(
            checkpoint, start, end, include_permissions=True
        )
        return checkpoint

    def _users_for_full_walk(self) -> Generator[OneDriveUser, None, None]:
        if not self.settings.all_users:
            for identifier in self.settings.users:
                user = self.ops.get_user(identifier=identifier)
                if user is None:
                    raise ConnectorValidationError(f"No user matches `{identifier}`.")
                yield user
            return
        next_link: str | None = None
        while True:
            page = self.ops.list_users(next_link=next_link)
            yield from page.users
            next_link = page.next_link
            if next_link is None:
                return

    def _retrieve_slim_drive(
        self,
        user: OneDriveUser,
        drive: OneDriveDrive,
        callback: IndexingHeartbeatInterface | None,
        *,
        include_permissions: bool,
    ) -> GenerateSlimDocumentOutput:
        root_access = (
            ExternalAccess(
                external_user_emails={user.user_principal_name.lower()},
                external_user_group_ids=set(),
                is_public=False,
            )
            if include_permissions
            else None
        )
        yield [user_root_node(user, drive, root_access)]
        self._folder_access.clear()
        cursor = build_drive_delta_start_url(
            f"{self.settings.graph_api_host}/{GRAPH_API_VERSION}",
            drive.id,
            page_size=self.settings.batch_size,
            select_fields=DRIVE_DELTA_SELECT_FIELDS,
        )
        while cursor:
            if callback and callback.should_stop():
                return
            result = self.ops.get_delta_page(
                drive_id=drive.id,
                page_url=cursor,
                page_size=self.settings.batch_size,
            )
            batch: list[SlimDocument | HierarchyNode] = []
            for item in _last_delta_item_occurrences(result.page.items):
                if item.is_tombstone:
                    continue
                if item.is_folder:
                    if not self._path_allowed(item):
                        continue
                    try:
                        access = (
                            self._item_access(user, drive, item, add_prefix=False)
                            if include_permissions
                            else None
                        )
                    except OneDriveGraphError as error:
                        if not self.settings.all_users or not _is_user_unavailable(
                            error
                        ):
                            raise
                        logger.info(
                            "OneDrive: skipping inaccessible folder %s (%s)",
                            item.id,
                            error.code,
                        )
                        continue
                    batch.append(folder_node(drive, item, access))
                    continue
                if not item.is_file or not self._item_allowed(item, None, None):
                    continue
                try:
                    access = (
                        self._item_access(user, drive, item, add_prefix=False)
                        if include_permissions
                        else get_ce_onedrive_access()
                    )
                except OneDriveGraphError as error:
                    if not self.settings.all_users or not _is_user_unavailable(error):
                        raise
                    logger.info(
                        "OneDrive: skipping inaccessible item %s (%s)",
                        item.id,
                        error.code,
                    )
                    continue
                batch.append(
                    SlimDocument(
                        id=item.id,
                        external_access=access,
                        parent_hierarchy_raw_node_id=item_parent_id(drive.id, item),
                        doc_created_at=item.created_datetime,
                    )
                )
            if batch:
                yield batch
            cursor = result.next_cursor

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        del start, end
        yield from self._retrieve_all_slim_docs(
            callback=callback, include_permissions=False
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        del start, end
        yield from self._retrieve_all_slim_docs(
            callback=callback, include_permissions=True
        )

    def _retrieve_all_slim_docs(
        self,
        *,
        callback: IndexingHeartbeatInterface | None,
        include_permissions: bool,
    ) -> GenerateSlimDocumentOutput:
        for user in self._users_for_full_walk():
            try:
                drive = self.ops.get_default_drive(user_id=user.id)
            except OneDriveGraphError as error:
                if not self.settings.all_users or not _is_user_unavailable(error):
                    raise
                logger.info(
                    "OneDrive: skipping inaccessible drive for %s (%s)",
                    user.user_principal_name,
                    error.code,
                )
                continue
            if drive is None:
                if not self.settings.all_users:
                    raise ConnectorValidationError(
                        f"`{user.user_principal_name}` has no OneDrive."
                    )
                continue
            try:
                yield from self._retrieve_slim_drive(
                    user,
                    drive,
                    callback,
                    include_permissions=include_permissions,
                )
            except OneDriveGraphError as error:
                if not self.settings.all_users or not _is_user_unavailable(error):
                    raise
                logger.info(
                    "OneDrive: skipping inaccessible delta for %s (%s)",
                    user.user_principal_name,
                    error.code,
                )
