from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
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
from onyx.connectors.onedrive.access import get_ce_onedrive_access
from onyx.connectors.onedrive.errors import OneDriveGraphError
from onyx.connectors.onedrive.models import (
    OneDriveCheckpoint,
    OneDriveDrive,
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


def _is_user_unavailable(error: OneDriveGraphError) -> bool:
    return error.status in USER_UNAVAILABLE_STATUSES


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


def user_root_node(user: OneDriveUser, drive: OneDriveDrive) -> HierarchyNode:
    return HierarchyNode(
        raw_node_id=drive_root_id(drive.id),
        raw_parent_id=None,
        display_name=user.display_name or user.user_principal_name,
        link=drive.web_url,
        node_type=HierarchyNodeType.MY_DRIVE,
        external_access=get_ce_onedrive_access(),
    )


def folder_node(drive: OneDriveDrive, item: DriveDeltaItem) -> HierarchyNode:
    return HierarchyNode(
        raw_node_id=hierarchy_item_id(drive.id, item.id),
        raw_parent_id=item_parent_id(drive.id, item),
        display_name=item.name or "",
        link=item.web_url,
        node_type=HierarchyNodeType.FOLDER,
        external_access=get_ce_onedrive_access(),
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
        external_access=get_ce_onedrive_access(),
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
    CredentialsConnector,
    CheckpointedConnector[OneDriveCheckpoint],
):
    def __init__(
        self,
        users: list[str] | None = None,
        all_users: bool = True,
        excluded_paths: list[str] | None = None,
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
            authority_host=authority_host.rstrip("/"),
            graph_api_host=graph_api_host.rstrip("/"),
            batch_size=batch_size,
        )
        _validate_user_scope(self.settings)
        resolve_microsoft_environment(
            self.settings.graph_api_host, self.settings.authority_host
        )
        self._ops: OneDriveSourceOperations | None = None

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
        checkpoint.seen_document_ids.clear()
        checkpoint.seen_hierarchy_raw_ids.clear()

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
        self, item: DriveDeltaItem, drive: OneDriveDrive
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
        return drive_item_document(drive_item, drive, content, parent)

    def _read_delta_page(
        self,
        checkpoint: OneDriveCheckpoint,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
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
        root_id = drive_root_id(drive.id)
        if root_id not in checkpoint.seen_hierarchy_raw_ids:
            yield user_root_node(user, drive)
            checkpoint.seen_hierarchy_raw_ids.add(root_id)
        checkpoint.delta_started = True
        checkpoint.delta_cursor = result.next_cursor
        if result.resynced:
            return
        for item in result.page.items:
            if item.is_tombstone:
                continue
            if item.is_folder:
                raw_id = hierarchy_item_id(drive.id, item.id)
                if (
                    not self._path_allowed(item)
                    or raw_id in checkpoint.seen_hierarchy_raw_ids
                ):
                    continue
                yield folder_node(drive, item)
                checkpoint.seen_hierarchy_raw_ids.add(raw_id)
                continue
            if not item.is_file or not self._item_allowed(item, start_at, end_at):
                continue
            if item.id in checkpoint.seen_document_ids:
                continue
            checkpoint.seen_document_ids.add(item.id)
            output = self._file_output(item, drive)
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
        yield from self._read_delta_page(checkpoint, start, end)
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
    ) -> GenerateSlimDocumentOutput:
        yield [user_root_node(user, drive)]
        cursor = build_drive_delta_start_url(
            f"{self.settings.graph_api_host}/{GRAPH_API_VERSION}",
            drive.id,
            page_size=self.settings.batch_size,
            select_fields=DRIVE_DELTA_SELECT_FIELDS,
        )
        seen_document_ids: set[str] = set()
        seen_hierarchy_raw_ids: set[str] = {drive_root_id(drive.id)}
        while cursor:
            if callback and callback.should_stop():
                return
            result = self.ops.get_delta_page(
                drive_id=drive.id,
                page_url=cursor,
                page_size=self.settings.batch_size,
            )
            batch: list[SlimDocument | HierarchyNode] = []
            for item in result.page.items:
                if item.is_tombstone:
                    continue
                if item.is_folder:
                    raw_id = hierarchy_item_id(drive.id, item.id)
                    if not self._path_allowed(item) or raw_id in seen_hierarchy_raw_ids:
                        continue
                    seen_hierarchy_raw_ids.add(raw_id)
                    batch.append(folder_node(drive, item))
                    continue
                if (
                    item.is_file
                    and item.id not in seen_document_ids
                    and self._item_allowed(item, None, None)
                ):
                    seen_document_ids.add(item.id)
                    batch.append(
                        SlimDocument(
                            id=item.id,
                            external_access=get_ce_onedrive_access(),
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
                yield from self._retrieve_slim_drive(user, drive, callback)
            except OneDriveGraphError as error:
                if not self.settings.all_users or not _is_user_unavailable(error):
                    raise
                logger.info(
                    "OneDrive: skipping inaccessible delta for %s (%s)",
                    user.user_principal_name,
                    error.code,
                )
