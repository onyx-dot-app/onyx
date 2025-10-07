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
from onyx.access.models import ExternalAccess
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
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


def gdrive_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[DocExternalAccess, None, None]:
    """
    Adds the external permissions to the documents in postgres
    if the document doesn't already exists in postgres, we create
    it in postgres so that when it gets created later, the permissions are
    already populated
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
