from collections.abc import Generator
from datetime import datetime
from datetime import timezone

from box_sdk_gen.client import BoxClient

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsIdsFunction
from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.connectors.box.connector import BoxConnector
from onyx.connectors.box.models import BoxFileType
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_external_access_for_raw_box_file(
    file: BoxFileType,
    company_domain: str | None,
    retriever_box_client: BoxClient | None,
    admin_box_client: BoxClient,
) -> ExternalAccess:
    """
    Extract permissions from a Box file's collaborations.

    Box permissions are managed through collaborations, which can be:
    - User collaborations: direct access for specific users (by email)
    - Group collaborations: access for groups (by group ID)
    - Public links: shared links that may be publicly accessible
    """
    file_id = file.get("id")
    if not file_id:
        raise ValueError("No file_id found in file")

    user_emails: set[str] = set()
    group_ids: set[str] = set()
    public = False

    # Use admin client to get permissions (has broader access)
    box_client = admin_box_client or retriever_box_client
    if not box_client:
        logger.warning(f"No Box client available for file {file_id}")
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=False,
        )

    try:
        # Box SDK v10 uses list_collaborations manager for getting file collaborations
        collaborations_response = (
            box_client.list_collaborations.get_file_collaborations(file_id=file_id)
        )

        for collaboration in collaborations_response.entries:
            accessible_by = collaboration.accessible_by

            if accessible_by:
                # User collaboration: extract email/login
                if hasattr(accessible_by, "login") and accessible_by.login:
                    user_emails.add(accessible_by.login)
                elif hasattr(accessible_by, "email") and accessible_by.email:
                    user_emails.add(accessible_by.email)

                # Group collaboration: groups have name but no login/email
                if hasattr(accessible_by, "name") and not hasattr(
                    accessible_by, "login"
                ):
                    if hasattr(accessible_by, "id") and accessible_by.id:
                        group_ids.add(str(accessible_by.id))

            # Public link collaboration: accessible_by is None for public links
            if accessible_by is None:
                if (
                    hasattr(collaboration, "status")
                    and collaboration.status == "accepted"
                    and file.get("shared_link")
                ):
                    public = True

    except Exception as e:
        # Sanitize error message to avoid leaking sensitive data (URLs, tokens, etc.)
        import re

        error_str = str(e)
        # Remove URLs
        error_str = re.sub(r"https?://[^\s]+", "[URL_REDACTED]", error_str)
        # Remove potential tokens (long alphanumeric strings)
        error_str = re.sub(r"\b[a-zA-Z0-9]{32,}\b", "[TOKEN_REDACTED]", error_str)

        # Check if this is a transient error that should be retried
        error_lower = error_str.lower()
        is_transient = any(
            indicator in error_lower
            for indicator in [
                "timeout",
                "connection",
                "503",
                "502",
                "500",
                "rate limit",
            ]
        )

        if is_transient:
            logger.warning(
                f"Transient error getting collaborations for Box file {file_id}: {error_str}. "
                "This may be retried on next sync."
            )
        else:
            logger.warning(
                f"Failed to get collaborations for Box file {file_id}: {error_str}. "
                "Returning minimal access (file owner retains access via retriever user)."
            )

    # Check for shared link (indicates potential public access)
    # Only mark as public if the shared link is actually public (access="open")
    # and not password-protected
    # Note: Box API may not return password field for security reasons, so we need
    # to fetch file details to check password protection, or be conservative
    shared_link = file.get("shared_link")

    # Always try to fetch the file directly to get the most up-to-date shared_link
    # (folder listing responses may not include shared_link or may have stale data)
    try:
        file_info = box_client.files.get_file_by_id(
            file_id=file_id, fields=["shared_link"]
        )
        if file_info.shared_link:
            # Convert Box SDK object to dict format for consistent handling
            sl = file_info.shared_link
            # Check if shared_link has the necessary attributes
            if hasattr(sl, "access") or hasattr(sl, "url"):
                access_value = None
                if hasattr(sl, "access"):
                    if hasattr(sl.access, "value"):
                        access_value = sl.access.value
                    else:
                        access_value = str(sl.access)

                shared_link = {
                    "url": sl.url if hasattr(sl, "url") else None,
                    "access": access_value,
                    "password": (sl.password if hasattr(sl, "password") else None),
                }
    except Exception as e:
        # If we can't fetch file details, fall back to shared_link from file dict
        # Log but continue with the shared_link from the file dict if available
        logger.debug(f"Could not fetch shared_link for file {file_id}: {e}")

    if shared_link:
        # shared_link can be a string (legacy) or a dict with access/password info
        if isinstance(shared_link, dict):
            access = shared_link.get("access")
            password = shared_link.get("password")
            # Handle both string and enum values for access
            # Box SDK may return enum objects, so convert to string for comparison
            access_str = str(access).lower() if access else None
            # Mark as public if access is "open" and not password-protected
            if access_str == "open":
                # If password is explicitly set and truthy, it's password-protected
                # If password is None/False or doesn't exist, assume it's public
                # (Box API may not always return password field)
                if not password:
                    public = True
            else:
                # Log when access is not "open" to help debug
                logger.debug(
                    f"File {file_id} has shared_link but access is '{access}' (str: '{access_str}'), not 'open'"
                )
        elif isinstance(shared_link, str):
            # Legacy: if it's just a URL string, we can't determine access level
            # Don't assume it's public - only mark as public if we found a public
            # collaboration above
            pass
    else:
        # Log when file has no shared_link to help debug
        logger.debug(f"File {file_id} has no shared_link")

    # If file doesn't have its own shared link, check parent folder's shared link
    # Files in public folders inherit the folder's public access
    if not public:
        parent = file.get("parent")
        if parent and isinstance(parent, dict):
            parent_id = parent.get("id")
            if parent_id:
                try:
                    # Fetch parent folder to check its shared link
                    parent_folder = box_client.folders.get_folder_by_id(
                        folder_id=parent_id, fields=["shared_link"]
                    )
                    if parent_folder.shared_link:
                        # Check if parent folder has a public shared link
                        parent_shared_link = parent_folder.shared_link

                        # Handle Box SDK object format
                        parent_access = None
                        parent_password = None

                        if hasattr(parent_shared_link, "access"):
                            # Box SDK object: access is an enum
                            access_value = parent_shared_link.access
                            if hasattr(access_value, "value"):
                                parent_access = access_value.value
                            else:
                                parent_access = str(access_value)
                        elif isinstance(parent_shared_link, dict):
                            # Dict format (from our conversion)
                            parent_access = parent_shared_link.get("access")

                        # Get password field
                        if hasattr(parent_shared_link, "password"):
                            parent_password = parent_shared_link.password
                        elif isinstance(parent_shared_link, dict):
                            parent_password = parent_shared_link.get("password")

                        # Mark as public if access is "open" and not password-protected
                        if parent_access == "open":
                            # If password is explicitly set and truthy, it's password-protected
                            # If password is None/False or doesn't exist, assume it's public
                            # (Box API may not always return password field)
                            if not parent_password:
                                public = True
                except Exception as e:
                    # If we can't fetch parent folder, log but don't fail
                    # This might happen if we don't have access to the parent folder
                    logger.debug(
                        f"Could not fetch parent folder {parent_id} for file {file_id}: {e}"
                    )

    return ExternalAccess(
        external_user_emails=user_emails,
        external_user_group_ids=group_ids,
        is_public=public,
    )


def _get_slim_doc_generator(
    cc_pair: ConnectorCredentialPair,
    box_connector: BoxConnector,
    callback: IndexingHeartbeatInterface | None = None,
) -> GenerateSlimDocumentOutput:
    current_time = datetime.now(timezone.utc)
    start_time = (
        cc_pair.last_time_perm_sync.replace(tzinfo=timezone.utc).timestamp()
        if cc_pair.last_time_perm_sync
        else 0.0
    )

    return box_connector.retrieve_all_slim_docs_perm_sync(
        start=start_time,
        end=current_time.timestamp(),
        callback=callback,
    )


def box_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None,
) -> Generator[DocExternalAccess, None, None]:
    """
    Sync Box file permissions to documents in the database.

    Retrieves slim documents from Box and extracts their permissions,
    yielding DocExternalAccess objects for each document with permissions.
    If a document doesn't exist yet, permissions are pre-populated
    so they're available when the document is created.
    """
    box_connector = BoxConnector(**cc_pair.connector.connector_specific_config)
    box_connector.load_credentials(cc_pair.credential.credential_json)

    slim_doc_generator = _get_slim_doc_generator(
        cc_pair, box_connector, callback=callback
    )

    for slim_doc_batch in slim_doc_generator:
        for slim_doc in slim_doc_batch:
            if callback:
                if callback.should_stop():
                    raise RuntimeError("box_doc_sync: Stop signal detected")

                callback.progress("box_doc_sync", 1)

            if slim_doc.external_access is None:
                logger.warning(f"No permissions found for document {slim_doc.id}")
                continue

            yield DocExternalAccess(
                doc_id=slim_doc.id,
                external_access=slim_doc.external_access,
            )
