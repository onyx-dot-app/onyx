from collections.abc import Generator
from datetime import datetime
from datetime import timezone

from ee.onyx.external_permissions.google_drive.models import GoogleDrivePermission
from ee.onyx.external_permissions.google_drive.models import PermissionType
from ee.onyx.external_permissions.google_drive.permission_retrieval import (
    get_permissions_by_ids,
)
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsIdsFunction
from onyx.access.models import DocExternalAccess
from onyx.access.models import ElementExternalAccess
from onyx.access.models import ExternalAccess
from onyx.access.models import NodeExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.models import HierarchyNode
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_slim_doc_generator(
    cc_pair: ConnectorCredentialPair,
    google_drive_connector: GoogleDriveConnector,
    callback: IndexingHeartbeatInterface | None = None,
) -> GenerateSlimDocumentOutput:
    current_time = datetime.now(timezone.utc)
    start_time = (
        cc_pair.last_time_perm_sync.replace(tzinfo=timezone.utc).timestamp()
        if cc_pair.last_time_perm_sync
        else 0.0
    )

    return google_drive_connector.retrieve_all_slim_docs_perm_sync(
        start=start_time,
        end=current_time.timestamp(),
        callback=callback,
    )


def _merge_permissions_lists(
    permission_lists: list[list[GoogleDrivePermission]],
) -> list[GoogleDrivePermission]:
    """
    Merge a list of permission lists into a single list of permissions.
    """
    seen_permission_ids: set[str] = set()
    merged_permissions: list[GoogleDrivePermission] = []
    for permission_list in permission_lists:
        for permission in permission_list:
            if permission.id not in seen_permission_ids:
                merged_permissions.append(permission)
                seen_permission_ids.add(permission.id)

    return merged_permissions


def get_external_access_for_raw_gdrive_file(
    file: GoogleDriveFileType,
    company_domain: str,
    retriever_drive_service: GoogleDriveService | None,
    admin_drive_service: GoogleDriveService,
) -> ExternalAccess:
    """
    Get the external access for a raw Google Drive file.

    Assumes the file we retrieved has EITHER `permissions` or `permission_ids`
    """
    doc_id = file.get("id")
    if not doc_id:
        raise ValueError("No doc_id found in file")

    permissions = file.get("permissions")
    permission_ids = file.get("permissionIds")
    drive_id = file.get("driveId")

    permissions_list: list[GoogleDrivePermission] = []
    if permissions:
        permissions_list = [
            GoogleDrivePermission.from_drive_permission(p) for p in permissions
        ]
    elif permission_ids:

        def _get_permissions(
            drive_service: GoogleDriveService,
        ) -> list[GoogleDrivePermission]:
            return get_permissions_by_ids(
                drive_service=drive_service,
                doc_id=doc_id,
                permission_ids=permission_ids,
            )

        permissions_list = _get_permissions(
            retriever_drive_service or admin_drive_service
        )
        if len(permissions_list) != len(permission_ids) and retriever_drive_service:
            logger.warning(
                f"Failed to get all permissions for file {doc_id} with retriever service, "
                "trying admin service"
            )
            backup_permissions_list = _get_permissions(admin_drive_service)
            permissions_list = _merge_permissions_lists(
                [permissions_list, backup_permissions_list]
            )

    folder_ids_to_inherit_permissions_from: set[str] = set()
    user_emails: set[str] = set()
    group_emails: set[str] = set()
    public = False

    for permission in permissions_list:
        # if the permission is inherited, do not add it directly to the file
        # instead, add the folder ID as a group that has access to the file
        # we will then handle mapping that folder to the list of Onyx users
        # in the group sync job
        # NOTE: this doesn't handle the case where a folder initially has no
        # permissioning, but then later that folder is shared with a user or group.
        # We could fetch all ancestors of the file to get the list of folders that
        # might affect the permissions of the file, but this will get replaced with
        # an audit-log based approach in the future so not doing it now.
        if permission.inherited_from:
            folder_ids_to_inherit_permissions_from.add(permission.inherited_from)

        if permission.type == PermissionType.USER:
            if permission.email_address:
                user_emails.add(permission.email_address)
            else:
                logger.error(
                    "Permission is type `user` but no email address is "
                    f"provided for document {doc_id}"
                    f"\n {permission}"
                )
        elif permission.type == PermissionType.GROUP:
            # groups are represented as email addresses within Drive
            if permission.email_address:
                group_emails.add(permission.email_address)
            else:
                logger.error(
                    "Permission is type `group` but no email address is "
                    f"provided for document {doc_id}"
                    f"\n {permission}"
                )
        elif permission.type == PermissionType.DOMAIN and company_domain:
            if permission.domain == company_domain:
                public = True
            else:
                logger.warning(
                    "Permission is type domain but does not match company domain:"
                    f"\n {permission}"
                )
        elif permission.type == PermissionType.ANYONE:
            public = True

    group_ids = (
        group_emails
        | folder_ids_to_inherit_permissions_from
        | ({drive_id} if drive_id is not None else set())
    )

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_ids,
        is_public=public,
    )


def get_external_access_for_folder(
    folder: GoogleDriveFileType,
    google_domain: str,
    drive_service: GoogleDriveService,
) -> ExternalAccess:
    """
    Extract ExternalAccess from a folder's permissions.

    This fetches permissions using the Drive API (via permissionIds) and extracts
    user emails, group emails, and public access status.

    Args:
        folder: The folder metadata from Google Drive API (must include permissionIds field)
        google_domain: The company's Google Workspace domain (e.g., "company.com")
        drive_service: Google Drive service for fetching permission details

    Returns:
        ExternalAccess with extracted permission info
    """
    folder_id = folder.get("id")
    if not folder_id:
        logger.warning("Folder missing ID, returning empty permissions")
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=False,
        )

    # Get permission IDs from folder metadata
    permission_ids = folder.get("permissionIds") or []
    if not permission_ids:
        logger.debug(f"No permissionIds found for folder {folder_id}")
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=False,
        )

    # Fetch full permission objects using the permission IDs
    permissions_list = get_permissions_by_ids(
        drive_service=drive_service,
        doc_id=folder_id,
        permission_ids=permission_ids,
    )

    user_emails: set[str] = set()
    group_emails: set[str] = set()
    is_public = False

    for permission in permissions_list:
        if permission.type == PermissionType.USER:
            if permission.email_address:
                user_emails.add(permission.email_address)
            else:
                logger.warning(f"User permission without email for folder {folder_id}")
        elif permission.type == PermissionType.GROUP:
            # Groups are represented as email addresses in Google Drive
            if permission.email_address:
                group_emails.add(permission.email_address)
            else:
                logger.warning(f"Group permission without email for folder {folder_id}")
        elif permission.type == PermissionType.DOMAIN:
            # Domain permission - check if it matches company domain
            if permission.domain == google_domain:
                # Only public if discoverable (allowFileDiscovery is not False)
                # If allowFileDiscovery is False, it's "link only" access
                is_public = permission.allow_file_discovery is not False
            else:
                logger.debug(
                    f"Domain permission for {permission.domain} does not match "
                    f"company domain {google_domain} for folder {folder_id}"
                )
        elif permission.type == PermissionType.ANYONE:
            # Only public if discoverable (allowFileDiscovery is not False)
            # If allowFileDiscovery is False, it's "link only" access
            is_public = permission.allow_file_discovery is not False

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_emails,
        is_public=is_public,
    )


def gdrive_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[ElementExternalAccess, None, None]:
    """
    Adds the external permissions to the documents and hierarchy nodes in postgres.
    If the document doesn't already exist in postgres, we create
    it in postgres so that when it gets created later, the permissions are
    already populated.
    """
    google_drive_connector = GoogleDriveConnector(
        **cc_pair.connector.connector_specific_config
    )
    google_drive_connector.load_credentials(cc_pair.credential.credential_json)

    slim_doc_generator = _get_slim_doc_generator(cc_pair, google_drive_connector)

    total_processed = 0
    for slim_doc_batch in slim_doc_generator:
        logger.info(f"Drive perm sync: Processing {len(slim_doc_batch)} documents")
        for slim_doc in slim_doc_batch:
            if callback:
                if callback.should_stop():
                    raise RuntimeError("gdrive_doc_sync: Stop signal detected")

                callback.progress("gdrive_doc_sync", 1)
            if isinstance(slim_doc, HierarchyNode):
                # Yield hierarchy node permissions to be processed in outer layer
                if slim_doc.external_access:
                    yield NodeExternalAccess(
                        external_access=slim_doc.external_access,
                        raw_node_id=slim_doc.raw_node_id,
                        source=DocumentSource.GOOGLE_DRIVE.value,
                    )
                continue
            if slim_doc.external_access is None:
                raise ValueError(
                    f"Drive perm sync: No external access for document {slim_doc.id}"
                )

            yield DocExternalAccess(
                external_access=slim_doc.external_access,
                doc_id=slim_doc.id,
            )
        total_processed += len(slim_doc_batch)
        logger.info(f"Drive perm sync: Processed {total_processed} total documents")
