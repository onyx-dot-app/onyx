from datetime import datetime
from datetime import timezone
from typing import Any

from danswer.access.models import DocExternalAccess
from danswer.access.models import ExternalAccess
from danswer.connectors.google_drive.connector import GoogleDriveConnector
from danswer.connectors.google_utils.google_utils import execute_paginated_retrieval
from danswer.connectors.google_utils.resources import get_drive_service
from danswer.connectors.interfaces import GenerateSlimDocumentOutput
from danswer.connectors.models import SlimDocument
from danswer.db.models import ConnectorCredentialPair
from danswer.utils.logger import setup_logger

logger = setup_logger()

_PERMISSION_ID_PERMISSION_MAP: dict[str, dict[str, Any]] = {}


def _get_slim_doc_generator(
    cc_pair: ConnectorCredentialPair,
    google_drive_connector: GoogleDriveConnector,
) -> GenerateSlimDocumentOutput:
    current_time = datetime.now(timezone.utc)
    start_time = (
        cc_pair.last_time_perm_sync.replace(tzinfo=timezone.utc).timestamp()
        if cc_pair.last_time_perm_sync
        else 0.0
    )

    return google_drive_connector.retrieve_all_slim_documents(
        start=start_time, end=current_time.timestamp()
    )


def _fetch_permissions_for_permission_ids(
    google_drive_connector: GoogleDriveConnector,
    permission_ids: list[str],
    permission_info: dict[str, Any],
) -> list[dict[str, Any]]:
    doc_id = permission_info.get("doc_id")
    if not permission_info or not doc_id:
        return []

    # Check cache first for all permission IDs
    permissions = [
        _PERMISSION_ID_PERMISSION_MAP[pid]
        for pid in permission_ids
        if pid in _PERMISSION_ID_PERMISSION_MAP
    ]

    # If we found all permissions in cache, return them
    if len(permissions) == len(permission_ids):
        return permissions

    owner_email = permission_info.get("owner_email")
    drive_service = get_drive_service(
        creds=google_drive_connector.creds,
        user_email=(owner_email or google_drive_connector.primary_admin_email),
    )

    # Otherwise, fetch all permissions and update cache
    fetched_permissions = execute_paginated_retrieval(
        retrieval_function=drive_service.permissions().list,
        list_key="permissions",
        fileId=doc_id,
        fields="permissions(id, emailAddress, type, domain)",
        supportsAllDrives=True,
    )

    permissions_for_doc_id = []
    # Update cache and return all permissions
    for permission in fetched_permissions:
        permissions_for_doc_id.append(permission)
        _PERMISSION_ID_PERMISSION_MAP[permission["id"]] = permission

    return permissions_for_doc_id


def _get_permissions_from_slim_doc(
    google_drive_connector: GoogleDriveConnector,
    slim_doc: SlimDocument,
) -> ExternalAccess:
    permission_info = slim_doc.perm_sync_data or {}

    permissions_list = permission_info.get("permissions", [])
    if not permissions_list:
        if permission_ids := permission_info.get("permission_ids"):
            permissions_list = _fetch_permissions_for_permission_ids(
                google_drive_connector=google_drive_connector,
                permission_ids=permission_ids,
                permission_info=permission_info,
            )
        if not permissions_list:
            logger.warning(f"No permissions found for document {slim_doc.id}")
            return ExternalAccess(
                external_user_emails=set(),
                external_user_group_ids=set(),
                is_public=False,
            )

    company_domain = google_drive_connector.google_domain
    user_emails: set[str] = set()
    group_emails: set[str] = set()
    public = False
    for permission in permissions_list:
        permission_type = permission["type"]
        if permission_type == "user":
            user_emails.add(permission["emailAddress"])
        elif permission_type == "group":
            group_emails.add(permission["emailAddress"])
        elif permission_type == "domain" and company_domain:
            if permission.get("domain") == company_domain:
                public = True
            else:
                logger.warning(
                    "Permission is type domain but does not match company domain:"
                    f"\n {permission}"
                )
        elif permission_type == "anyone":
            public = True

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_emails,
        is_public=public,
    )


def gdrive_doc_sync(
    cc_pair: ConnectorCredentialPair,
) -> list[DocExternalAccess]:
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

    document_external_accesses = []
    for slim_doc_batch in slim_doc_generator:
        for slim_doc in slim_doc_batch:
            ext_access = _get_permissions_from_slim_doc(
                google_drive_connector=google_drive_connector,
                slim_doc=slim_doc,
            )
            document_external_accesses.append(
                DocExternalAccess(
                    external_access=ext_access,
                    doc_id=slim_doc.id,
                )
            )
    return document_external_accesses
