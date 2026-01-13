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
        collaborations_response = box_client.collaborations.get_file_collaborations(
            file_id=file_id
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
        logger.warning(
            f"Failed to get collaborations for Box file {file_id}: {e}. "
            "Returning minimal access (file owner retains access via retriever user)."
        )

    # Check for shared link (indicates potential public access)
    # Note: Box shared links can be public or password-protected, but we
    # treat any shared link as potentially public for access control
    if file.get("shared_link"):
        public = True

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
