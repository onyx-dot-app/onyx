import io
import json
import math
import mimetypes
import os
import zipfile
from io import BytesIO
from typing import Any
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
from fastapi import UploadFile
from google.oauth2.credentials import Credentials  # type: ignore
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_chat_accessible_user
from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import DISABLE_AUTH
from onyx.configs.app_configs import ENABLED_CONNECTOR_TYPES
from onyx.configs.app_configs import MOCK_CONNECTOR_FILE_PATH
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import MilestoneRecordType
from onyx.configs.constants import ONYX_METADATA_FILENAME
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.factory import validate_ccpair_for_user
from onyx.connectors.google_utils.google_auth import (
    get_google_oauth_creds,
)
from onyx.connectors.google_utils.google_kv import (
    build_service_account_creds,
)
from onyx.connectors.google_utils.google_kv import (
    delete_google_app_cred,
)
from onyx.connectors.google_utils.google_kv import (
    delete_service_account_key,
)
from onyx.connectors.google_utils.google_kv import get_auth_url
from onyx.connectors.google_utils.google_kv import (
    get_google_app_cred,
)
from onyx.connectors.google_utils.google_kv import (
    get_service_account_key,
)
from onyx.connectors.google_utils.google_kv import (
    update_credential_access_tokens,
)
from onyx.connectors.google_utils.google_kv import (
    upsert_google_app_cred,
)
from onyx.connectors.google_utils.google_kv import (
    upsert_service_account_key,
)
from onyx.connectors.google_utils.google_kv import verify_csrf
from onyx.connectors.google_utils.shared_constants import DB_CREDENTIALS_DICT_TOKEN_KEY
from onyx.connectors.google_utils.shared_constants import (
    GoogleOAuthAuthenticationMethod,
)
from onyx.db.connector import create_connector
from onyx.db.connector import delete_connector
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector import fetch_connectors
from onyx.db.connector import get_connector_credential_ids
from onyx.db.connector import mark_ccpair_with_indexing_trigger
from onyx.db.connector import update_connector
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.connector_credential_pair import (
    fetch_connector_credential_pair_for_connector,
)
from onyx.db.connector_credential_pair import get_cc_pair_groups_for_ids
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_user
from onyx.db.connector_credential_pair import (
    get_connector_credential_pairs_for_user_parallel,
)
from onyx.db.credentials import cleanup_gmail_credentials
from onyx.db.credentials import cleanup_google_drive_credentials
from onyx.db.credentials import create_credential
from onyx.db.credentials import delete_service_account_credentials
from onyx.db.credentials import fetch_credential_by_id_for_user
from onyx.db.deletion_attempt import check_deletion_attempt_is_allowed
from onyx.db.document import get_document_counts_for_all_cc_pairs
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingMode
from onyx.db.federated import fetch_all_federated_connectors_parallel
from onyx.db.index_attempt import get_index_attempts_for_cc_pair
from onyx.db.index_attempt import get_latest_index_attempts_by_status
from onyx.db.index_attempt import get_latest_index_attempts_parallel
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import FederatedConnector
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexingStatus
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.documents.models import AuthStatus
from onyx.server.documents.models import AuthUrl
from onyx.server.documents.models import ConnectorCredentialPairIdentifier
from onyx.server.documents.models import ConnectorIndexingStatusLite
from onyx.server.documents.models import ConnectorIndexingStatusLiteResponse
from onyx.server.documents.models import ConnectorSnapshot
from onyx.server.documents.models import ConnectorStatus
from onyx.server.documents.models import ConnectorUpdateRequest
from onyx.server.documents.models import CredentialBase
from onyx.server.documents.models import CredentialSnapshot
from onyx.server.documents.models import DocsCountOperator
from onyx.server.documents.models import FailedConnectorIndexingStatus
from onyx.server.documents.models import FileUploadResponse
from onyx.server.documents.models import GDriveCallback
from onyx.server.documents.models import GmailCallback
from onyx.server.documents.models import GoogleAppCredentials
from onyx.server.documents.models import GoogleServiceAccountCredentialRequest
from onyx.server.documents.models import GoogleServiceAccountKey
from onyx.server.documents.models import IndexingStatusRequest
from onyx.server.documents.models import ObjectCreationIdResponse
from onyx.server.documents.models import RunConnectorRequest
from onyx.server.documents.models import SourceSummary
from onyx.server.federated.models import FederatedConnectorStatus
from onyx.server.models import StatusResponse
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import create_milestone_and_report
from onyx.utils.threadpool_concurrency import CallableProtocol
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_GMAIL_CREDENTIAL_ID_COOKIE_NAME = "gmail_credential_id"
_GOOGLE_DRIVE_CREDENTIAL_ID_COOKIE_NAME = "google_drive_credential_id"
_INDEXING_STATUS_PAGE_SIZE = 10

SEEN_ZIP_DETAIL = "Only one zip file is allowed per file connector, \
use the ingestion APIs for multiple files"

router = APIRouter(prefix="/manage")


"""Admin only API endpoints"""


@router.get("/admin/connector/gmail/app-credential")
def check_google_app_gmail_credentials_exist(
    _: User = Depends(current_curator_or_admin_user),
) -> dict[str, str]:
    try:
        return {"client_id": get_google_app_cred(DocumentSource.GMAIL).web.client_id}
    except KvKeyNotFoundError:
        raise HTTPException(status_code=404, detail="Google App Credentials not found")


@router.put("/admin/connector/gmail/app-credential")
def upsert_google_app_gmail_credentials(
    app_credentials: GoogleAppCredentials, _: User = Depends(current_admin_user)
) -> StatusResponse:
    try:
        upsert_google_app_cred(app_credentials, DocumentSource.GMAIL)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StatusResponse(
        success=True, message="Successfully saved Google App Credentials"
    )


@router.delete("/admin/connector/gmail/app-credential")
def delete_google_app_gmail_credentials(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    try:
        delete_google_app_cred(DocumentSource.GMAIL)
        cleanup_gmail_credentials(db_session=db_session)
    except KvKeyNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StatusResponse(
        success=True, message="Successfully deleted Google App Credentials"
    )


@router.get("/admin/connector/google-drive/app-credential")
def check_google_app_credentials_exist(
    _: User = Depends(current_curator_or_admin_user),
) -> dict[str, str]:
    try:
        return {
            "client_id": get_google_app_cred(DocumentSource.GOOGLE_DRIVE).web.client_id
        }
    except KvKeyNotFoundError:
        raise HTTPException(status_code=404, detail="Google App Credentials not found")


@router.put("/admin/connector/google-drive/app-credential")
def upsert_google_app_credentials(
    app_credentials: GoogleAppCredentials, _: User = Depends(current_admin_user)
) -> StatusResponse:
    try:
        upsert_google_app_cred(app_credentials, DocumentSource.GOOGLE_DRIVE)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StatusResponse(
        success=True, message="Successfully saved Google App Credentials"
    )


@router.delete("/admin/connector/google-drive/app-credential")
def delete_google_app_credentials(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    try:
        delete_google_app_cred(DocumentSource.GOOGLE_DRIVE)
        cleanup_google_drive_credentials(db_session=db_session)
    except KvKeyNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StatusResponse(
        success=True, message="Successfully deleted Google App Credentials"
    )


@router.get("/admin/connector/gmail/service-account-key")
def check_google_service_gmail_account_key_exist(
    _: User = Depends(current_curator_or_admin_user),
) -> dict[str, str]:
    try:
        return {
            "service_account_email": get_service_account_key(
                DocumentSource.GMAIL
            ).client_email
        }
    except KvKeyNotFoundError:
        raise HTTPException(
            status_code=404, detail="Google Service Account Key not found"
        )


@router.put("/admin/connector/gmail/service-account-key")
def upsert_google_service_gmail_account_key(
    service_account_key: GoogleServiceAccountKey, _: User = Depends(current_admin_user)
) -> StatusResponse:
    try:
        upsert_service_account_key(service_account_key, DocumentSource.GMAIL)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StatusResponse(
        success=True, message="Successfully saved Google Service Account Key"
    )


@router.delete("/admin/connector/gmail/service-account-key")
def delete_google_service_gmail_account_key(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    try:
        delete_service_account_key(DocumentSource.GMAIL)
        cleanup_gmail_credentials(db_session=db_session)
    except KvKeyNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StatusResponse(
        success=True, message="Successfully deleted Google Service Account Key"
    )


@router.get("/admin/connector/google-drive/service-account-key")
def check_google_service_account_key_exist(
    _: User = Depends(current_curator_or_admin_user),
) -> dict[str, str]:
    try:
        return {
            "service_account_email": get_service_account_key(
                DocumentSource.GOOGLE_DRIVE
            ).client_email
        }
    except KvKeyNotFoundError:
        raise HTTPException(
            status_code=404, detail="Google Service Account Key not found"
        )


@router.put("/admin/connector/google-drive/service-account-key")
def upsert_google_service_account_key(
    service_account_key: GoogleServiceAccountKey, _: User = Depends(current_admin_user)
) -> StatusResponse:
    try:
        upsert_service_account_key(service_account_key, DocumentSource.GOOGLE_DRIVE)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StatusResponse(
        success=True, message="Successfully saved Google Service Account Key"
    )


@router.delete("/admin/connector/google-drive/service-account-key")
def delete_google_service_account_key(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    try:
        delete_service_account_key(DocumentSource.GOOGLE_DRIVE)
        cleanup_google_drive_credentials(db_session=db_session)
    except KvKeyNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StatusResponse(
        success=True, message="Successfully deleted Google Service Account Key"
    )


@router.put("/admin/connector/google-drive/service-account-credential")
def upsert_service_account_credential(
    service_account_credential_request: GoogleServiceAccountCredentialRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> ObjectCreationIdResponse:
    """Special API which allows the creation of a credential for a service account.
    Combines the input with the saved service account key to create an entry in the
    `Credential` table."""
    try:
        credential_base = build_service_account_creds(
            DocumentSource.GOOGLE_DRIVE,
            primary_admin_email=service_account_credential_request.google_primary_admin,
            name="Service Account (uploaded)",
        )
    except KvKeyNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # first delete all existing service account credentials
    delete_service_account_credentials(user, db_session, DocumentSource.GOOGLE_DRIVE)
    # `user=None` since this credential is not a personal credential
    credential = create_credential(
        credential_data=credential_base, user=user, db_session=db_session
    )
    return ObjectCreationIdResponse(id=credential.id)


@router.put("/admin/connector/gmail/service-account-credential")
def upsert_gmail_service_account_credential(
    service_account_credential_request: GoogleServiceAccountCredentialRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> ObjectCreationIdResponse:
    """Special API which allows the creation of a credential for a service account.
    Combines the input with the saved service account key to create an entry in the
    `Credential` table."""
    try:
        credential_base = build_service_account_creds(
            DocumentSource.GMAIL,
            primary_admin_email=service_account_credential_request.google_primary_admin,
        )
    except KvKeyNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # first delete all existing service account credentials
    delete_service_account_credentials(user, db_session, DocumentSource.GMAIL)
    # `user=None` since this credential is not a personal credential
    credential = create_credential(
        credential_data=credential_base, user=user, db_session=db_session
    )
    return ObjectCreationIdResponse(id=credential.id)


@router.get("/admin/connector/google-drive/check-auth/{credential_id}")
def check_drive_tokens(
    credential_id: int,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> AuthStatus:
    db_credentials = fetch_credential_by_id_for_user(credential_id, user, db_session)
    if (
        not db_credentials
        or DB_CREDENTIALS_DICT_TOKEN_KEY not in db_credentials.credential_json
    ):
        return AuthStatus(authenticated=False)
    token_json_str = str(db_credentials.credential_json[DB_CREDENTIALS_DICT_TOKEN_KEY])
    google_drive_creds = get_google_oauth_creds(
        token_json_str=token_json_str,
        source=DocumentSource.GOOGLE_DRIVE,
    )
    if google_drive_creds is None:
        return AuthStatus(authenticated=False)
    return AuthStatus(authenticated=True)


def extract_zip_metadata(zf: zipfile.ZipFile) -> dict[str, Any]:
    zip_metadata = {}
    try:
        metadata_file_info = zf.getinfo(ONYX_METADATA_FILENAME)
        with zf.open(metadata_file_info, "r") as metadata_file:
            try:
                zip_metadata = json.load(metadata_file)
                if isinstance(zip_metadata, list):
                    # convert list of dicts to dict of dicts
                    # Use just the basename for matching since metadata may not include
                    # the full path within the ZIP file
                    zip_metadata = {d["filename"]: d for d in zip_metadata}
            except json.JSONDecodeError as e:
                logger.warning(f"Unable to load {ONYX_METADATA_FILENAME}: {e}")
                # should fail loudly here to let users know that their metadata
                # file is not valid JSON
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to load {ONYX_METADATA_FILENAME}: {e}",
                )
    except KeyError:
        logger.info(f"No {ONYX_METADATA_FILENAME} file")
    return zip_metadata


def is_zip_file(file: UploadFile) -> bool:
    """
    Check if the file is a zip file by content type or filename.
    """
    return bool(
        (
            file.content_type
            and file.content_type.startswith(
                (
                    "application/zip",
                    "application/x-zip-compressed",  # May be this in Windows
                    "application/x-zip",
                    "multipart/x-zip",
                )
            )
        )
        or (file.filename and file.filename.lower().endswith(".zip"))
    )


def upload_files(
    files: list[UploadFile], file_origin: FileOrigin = FileOrigin.CONNECTOR
) -> FileUploadResponse:
    for file in files:
        if not file.filename:
            raise HTTPException(status_code=400, detail="File name cannot be empty")

    # Skip directories and known macOS metadata entries
    def should_process_file(file_path: str) -> bool:
        normalized_path = os.path.normpath(file_path)
        return not any(part.startswith(".") for part in normalized_path.split(os.sep))

    deduped_file_paths = []
    deduped_file_names = []
    zip_metadata = {}
    try:
        file_store = get_default_file_store()
        seen_zip = False
        for file in files:
            if is_zip_file(file):
                if seen_zip:
                    raise HTTPException(status_code=400, detail=SEEN_ZIP_DETAIL)
                seen_zip = True
                with zipfile.ZipFile(file.file, "r") as zf:
                    zip_metadata = extract_zip_metadata(zf)
                    for file_info in zf.namelist():
                        if zf.getinfo(file_info).is_dir():
                            continue

                        if not should_process_file(file_info):
                            continue

                        sub_file_bytes = zf.read(file_info)

                        mime_type, __ = mimetypes.guess_type(file_info)
                        if mime_type is None:
                            mime_type = "application/octet-stream"

                        file_id = file_store.save_file(
                            content=BytesIO(sub_file_bytes),
                            display_name=os.path.basename(file_info),
                            file_origin=FileOrigin.CONNECTOR,
                            file_type=mime_type,
                        )
                        deduped_file_paths.append(file_id)
                        deduped_file_names.append(os.path.basename(file_info))
                continue

            # For mypy, actual check happens at start of function
            assert file.filename is not None

            # Special handling for doc files - only store the plaintext version
            file_type = mime_type_to_chat_file_type(file.content_type)
            if file_type == ChatFileType.DOC:
                extracted_text = extract_file_text(file.file, file.filename or "")
                text_file_id = file_store.save_file(
                    content=io.BytesIO(extracted_text.encode()),
                    display_name=file.filename,
                    file_origin=file_origin,
                    file_type="text/plain",
                )
                deduped_file_paths.append(text_file_id)
                deduped_file_names.append(file.filename)
                continue

            # Default handling for all other file types
            file_id = file_store.save_file(
                content=file.file,
                display_name=file.filename,
                file_origin=FileOrigin.CONNECTOR,
                file_type=file.content_type or "text/plain",
            )
            deduped_file_paths.append(file_id)
            deduped_file_names.append(file.filename)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return FileUploadResponse(
        file_paths=deduped_file_paths,
        file_names=deduped_file_names,
        zip_metadata=zip_metadata,
    )


@router.post("/admin/connector/file/upload")
def upload_files_api(
    files: list[UploadFile],
    _: User = Depends(current_curator_or_admin_user),
) -> FileUploadResponse:
    return upload_files(files, FileOrigin.OTHER)


@router.get("/admin/connector")
def get_connectors_by_credential(
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
    credential: int | None = None,
) -> list[ConnectorSnapshot]:
    """Get a list of connectors. Allow filtering by a specific credential id."""

    connectors = fetch_connectors(db_session)

    filtered_connectors = []
    for connector in connectors:
        if connector.source == DocumentSource.INGESTION_API:
            # don't include INGESTION_API, as it's a system level
            # connector not manageable by the user
            continue

        if credential is not None:
            found = False
            for cc_pair in connector.credentials:
                if credential == cc_pair.credential_id:
                    found = True
                    break

            if not found:
                continue

        filtered_connectors.append(ConnectorSnapshot.from_connector_db_model(connector))

    return filtered_connectors


# Retrieves most recent failure cases for connectors that are currently failing
@router.get("/admin/connector/failed-indexing-status")
def get_currently_failed_indexing_status(
    secondary_index: bool = False,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
    get_editable: bool = Query(
        False, description="If true, return editable document sets"
    ),
) -> list[FailedConnectorIndexingStatus]:
    # Get the latest failed indexing attempts
    latest_failed_indexing_attempts = get_latest_index_attempts_by_status(
        secondary_index=secondary_index,
        db_session=db_session,
        status=IndexingStatus.FAILED,
    )

    # Get the latest successful indexing attempts
    latest_successful_indexing_attempts = get_latest_index_attempts_by_status(
        secondary_index=secondary_index,
        db_session=db_session,
        status=IndexingStatus.SUCCESS,
    )

    # Get all connector credential pairs
    cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        get_editable=get_editable,
    )

    # Filter out failed attempts that have a more recent successful attempt
    filtered_failed_attempts = [
        failed_attempt
        for failed_attempt in latest_failed_indexing_attempts
        if not any(
            success_attempt.connector_credential_pair_id
            == failed_attempt.connector_credential_pair_id
            and success_attempt.time_updated > failed_attempt.time_updated
            for success_attempt in latest_successful_indexing_attempts
        )
    ]

    # Filter cc_pairs to include only those with failed attempts
    cc_pairs = [
        cc_pair
        for cc_pair in cc_pairs
        if any(
            attempt.connector_credential_pair == cc_pair
            for attempt in filtered_failed_attempts
        )
    ]

    # Create a mapping of cc_pair_id to its latest failed index attempt
    cc_pair_to_latest_index_attempt = {
        attempt.connector_credential_pair_id: attempt
        for attempt in filtered_failed_attempts
    }

    indexing_statuses = []

    for cc_pair in cc_pairs:
        # Skip DefaultCCPair
        if cc_pair.name == "DefaultCCPair":
            continue

        latest_index_attempt = cc_pair_to_latest_index_attempt.get(cc_pair.id)

        indexing_statuses.append(
            FailedConnectorIndexingStatus(
                cc_pair_id=cc_pair.id,
                name=cc_pair.name,
                error_msg=(
                    latest_index_attempt.error_msg if latest_index_attempt else None
                ),
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
                is_deletable=check_deletion_attempt_is_allowed(
                    connector_credential_pair=cc_pair,
                    db_session=db_session,
                    allow_scheduled=True,
                )
                is None,
            )
        )

    return indexing_statuses


@router.get("/admin/connector/status")
def get_connector_status(
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[ConnectorStatus]:
    # This method is only used document set and group creation/editing
    # Therefore, it is okay to get non-editable, but public cc_pairs
    cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        eager_load_connector=True,
        eager_load_credential=True,
        get_editable=False,
    )

    group_cc_pair_relationships = get_cc_pair_groups_for_ids(
        db_session=db_session,
        cc_pair_ids=[cc_pair.id for cc_pair in cc_pairs],
    )
    group_cc_pair_relationships_dict: dict[int, list[int]] = {}
    for relationship in group_cc_pair_relationships:
        group_cc_pair_relationships_dict.setdefault(relationship.cc_pair_id, []).append(
            relationship.user_group_id
        )

    return [
        ConnectorStatus(
            cc_pair_id=cc_pair.id,
            name=cc_pair.name,
            connector=ConnectorSnapshot.from_connector_db_model(cc_pair.connector),
            credential=CredentialSnapshot.from_credential_db_model(cc_pair.credential),
            access_type=cc_pair.access_type,
            groups=group_cc_pair_relationships_dict.get(cc_pair.id, []),
        )
        for cc_pair in cc_pairs
        if cc_pair.name != "DefaultCCPair" and cc_pair.connector and cc_pair.credential
    ]


@router.post("/admin/connector/indexing-status")
def get_connector_indexing_status(
    request: IndexingStatusRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[ConnectorIndexingStatusLiteResponse]:
    tenant_id = get_current_tenant_id()

    # NOTE: If the connector is deleting behind the scenes,
    # accessing cc_pairs can be inconsistent and members like
    # connector or credential may be None.
    # Additional checks are done to make sure the connector and credential still exist.
    # TODO: make this one query ... possibly eager load or wrap in a read transaction
    # to avoid the complexity of trying to error check throughout the function

    # see https://stackoverflow.com/questions/75758327/
    # sqlalchemy-method-connection-for-bind-is-already-in-progress
    # for why we can't pass in the current db_session to these functions

    if MOCK_CONNECTOR_FILE_PATH:
        import json

        with open(MOCK_CONNECTOR_FILE_PATH, "r") as f:
            raw_data = json.load(f)
            connector_indexing_statuses = [
                ConnectorIndexingStatusLite(**status) for status in raw_data
            ]
        return [
            ConnectorIndexingStatusLiteResponse(
                source=DocumentSource.FILE,
                summary=SourceSummary(
                    total_connectors=100,
                    active_connectors=100,
                    public_connectors=100,
                    total_docs_indexed=100000,
                ),
                current_page=1,
                total_pages=1,
                indexing_statuses=connector_indexing_statuses,
            )
        ]

    parallel_functions: list[tuple[CallableProtocol, tuple[Any, ...]]] = [
        # Get editable connector/credential pairs
        (
            get_connector_credential_pairs_for_user_parallel,
            (user, True, None, True, True, True, True, request.source),
        ),
        # Get federated connectors
        (fetch_all_federated_connectors_parallel, ()),
        # Get most recent index attempts
        (get_latest_index_attempts_parallel, (request.secondary_index, True, False)),
        # Get most recent finished index attempts
        (get_latest_index_attempts_parallel, (request.secondary_index, True, True)),
    ]

    if (user is None and DISABLE_AUTH) or (user and user.role == UserRole.ADMIN):
        # For Admin users, we already got all the cc pair in editable_cc_pairs
        # its not needed to get them again
        (
            editable_cc_pairs,
            federated_connectors,
            latest_index_attempts,
            latest_finished_index_attempts,
        ) = run_functions_tuples_in_parallel(parallel_functions)
        non_editable_cc_pairs = []
    else:
        parallel_functions.append(
            # Get non-editable connector/credential pairs
            (
                get_connector_credential_pairs_for_user_parallel,
                (user, False, None, True, True, True, True, request.source),
            ),
        )

        (
            editable_cc_pairs,
            federated_connectors,
            latest_index_attempts,
            latest_finished_index_attempts,
            non_editable_cc_pairs,
        ) = run_functions_tuples_in_parallel(parallel_functions)

    # Cast results to proper types
    non_editable_cc_pairs = cast(list[ConnectorCredentialPair], non_editable_cc_pairs)
    editable_cc_pairs = cast(list[ConnectorCredentialPair], editable_cc_pairs)
    federated_connectors = cast(list[FederatedConnector], federated_connectors)
    latest_index_attempts = cast(list[IndexAttempt], latest_index_attempts)
    latest_finished_index_attempts = cast(
        list[IndexAttempt], latest_finished_index_attempts
    )

    document_count_info = get_document_counts_for_all_cc_pairs(db_session)

    # Create lookup dictionaries for efficient access
    cc_pair_to_document_cnt: dict[tuple[int, int], int] = {
        (connector_id, credential_id): cnt
        for connector_id, credential_id, cnt in document_count_info
    }

    cc_pair_to_latest_index_attempt: dict[tuple[int, int], IndexAttempt] = {
        (
            attempt.connector_credential_pair.connector_id,
            attempt.connector_credential_pair.credential_id,
        ): attempt
        for attempt in latest_index_attempts
    }

    cc_pair_to_latest_finished_index_attempt: dict[tuple[int, int], IndexAttempt] = {
        (
            attempt.connector_credential_pair.connector_id,
            attempt.connector_credential_pair.credential_id,
        ): attempt
        for attempt in latest_finished_index_attempts
    }

    def build_connector_indexing_status(
        cc_pair: ConnectorCredentialPair,
        is_editable: bool,
    ) -> ConnectorIndexingStatusLite | None:
        # TODO remove this to enable ingestion API
        if cc_pair.name == "DefaultCCPair":
            return None

        latest_attempt = cc_pair_to_latest_index_attempt.get(
            (cc_pair.connector_id, cc_pair.credential_id)
        )
        latest_finished_attempt = cc_pair_to_latest_finished_index_attempt.get(
            (cc_pair.connector_id, cc_pair.credential_id)
        )
        doc_count = cc_pair_to_document_cnt.get(
            (cc_pair.connector_id, cc_pair.credential_id), 0
        )

        return _get_connector_indexing_status_lite(
            cc_pair, latest_attempt, latest_finished_attempt, is_editable, doc_count
        )

    # Process editable cc_pairs
    editable_statuses: list[ConnectorIndexingStatusLite] = []
    for cc_pair in editable_cc_pairs:
        status = build_connector_indexing_status(cc_pair, True)
        if status:
            editable_statuses.append(status)

    # Process non-editable cc_pairs
    non_editable_statuses: list[ConnectorIndexingStatusLite] = []
    for cc_pair in non_editable_cc_pairs:
        status = build_connector_indexing_status(cc_pair, False)
        if status:
            non_editable_statuses.append(status)

    # Process federated connectors
    federated_statuses: list[FederatedConnectorStatus] = []
    for federated_connector in federated_connectors:
        federated_status = FederatedConnectorStatus(
            id=federated_connector.id,
            source=federated_connector.source,
            name=f"{federated_connector.source.replace('_', ' ').title()}",
        )

        federated_statuses.append(federated_status)

    source_to_summary: dict[DocumentSource, SourceSummary] = {}

    # Apply filters only if any are provided
    has_filters = bool(
        request.access_type_filters
        or request.last_status_filters
        or (
            request.docs_count_operator is not None
            and request.docs_count_value is not None
        )
        or request.name_filter
    )

    if has_filters:
        editable_statuses = _apply_connector_status_filters(
            editable_statuses,
            request.access_type_filters,
            request.last_status_filters,
            request.docs_count_operator,
            request.docs_count_value,
            request.name_filter,
        )
        non_editable_statuses = _apply_connector_status_filters(
            non_editable_statuses,
            request.access_type_filters,
            request.last_status_filters,
            request.docs_count_operator,
            request.docs_count_value,
            request.name_filter,
        )
        federated_statuses = _apply_federated_connector_status_filters(
            federated_statuses,
            request.name_filter,
        )

    # Calculate source summary
    for connector_status in (
        editable_statuses + non_editable_statuses + federated_statuses
    ):
        if isinstance(connector_status, FederatedConnectorStatus):
            source = connector_status.source.to_non_federated_source()
        else:
            source = connector_status.source

        # Skip if source is None (federated connectors without mapping)
        if source is None:
            continue

        if source not in source_to_summary:
            source_to_summary[source] = SourceSummary(
                total_connectors=0,
                active_connectors=0,
                public_connectors=0,
                total_docs_indexed=0,
            )
        source_to_summary[source].total_connectors += 1
        if isinstance(connector_status, ConnectorIndexingStatusLite):
            if connector_status.cc_pair_status == ConnectorCredentialPairStatus.ACTIVE:
                source_to_summary[source].active_connectors += 1
            if connector_status.access_type == AccessType.PUBLIC:
                source_to_summary[source].public_connectors += 1
            source_to_summary[
                source
            ].total_docs_indexed += connector_status.docs_indexed

    # Track admin page visit for analytics
    create_milestone_and_report(
        user=user,
        distinct_id=user.email if user else tenant_id or "N/A",
        event_type=MilestoneRecordType.VISITED_ADMIN_PAGE,
        properties=None,
        db_session=db_session,
    )

    # Group statuses by source for pagination
    source_to_all_statuses: dict[
        DocumentSource, list[ConnectorIndexingStatusLite | FederatedConnectorStatus]
    ] = {}
    # Group by source
    for connector_status in (
        editable_statuses + non_editable_statuses + federated_statuses
    ):
        if isinstance(connector_status, FederatedConnectorStatus):
            source = connector_status.source.to_non_federated_source()
        else:
            source = connector_status.source

        # Skip if source is None (federated connectors without mapping)
        if source is None:
            continue

        if source not in source_to_all_statuses:
            source_to_all_statuses[source] = []
        source_to_all_statuses[source].append(connector_status)

    # Create paginated response objects by source
    response_list: list[ConnectorIndexingStatusLiteResponse] = []

    source_list = list(source_to_all_statuses.keys())
    source_list.sort()

    for source in source_list:
        statuses = source_to_all_statuses[source]
        # Get current page for this source (default to page 1, 1-indexed)
        current_page = request.source_to_page.get(source, 1)

        # Calculate start and end indices for pagination (convert to 0-indexed)
        start_idx = (current_page - 1) * _INDEXING_STATUS_PAGE_SIZE
        end_idx = start_idx + _INDEXING_STATUS_PAGE_SIZE

        if request.get_all_connectors:
            page_statuses = statuses
        else:
            # Get the page slice for this source
            page_statuses = statuses[start_idx:end_idx]

        # Create response object for this source
        if page_statuses:  # Only include sources that have data on this page
            response_list.append(
                ConnectorIndexingStatusLiteResponse(
                    source=source,
                    summary=source_to_summary[source],
                    current_page=current_page,
                    total_pages=math.ceil(len(statuses) / _INDEXING_STATUS_PAGE_SIZE),
                    indexing_statuses=page_statuses,
                )
            )

    return response_list


def _get_connector_indexing_status_lite(
    cc_pair: ConnectorCredentialPair,
    latest_index_attempt: IndexAttempt | None,
    latest_finished_index_attempt: IndexAttempt | None,
    is_editable: bool,
    document_cnt: int,
) -> ConnectorIndexingStatusLite | None:
    # TODO remove this to enable ingestion API
    if cc_pair.name == "DefaultCCPair":
        return None

    connector = cc_pair.connector
    credential = cc_pair.credential
    if not connector or not credential:
        # This may happen if background deletion is happening
        return None

    in_progress = bool(
        latest_index_attempt
        and latest_index_attempt.status == IndexingStatus.IN_PROGRESS
    )

    return ConnectorIndexingStatusLite(
        cc_pair_id=cc_pair.id,
        name=cc_pair.name,
        source=cc_pair.connector.source,
        access_type=cc_pair.access_type,
        cc_pair_status=cc_pair.status,
        is_editable=is_editable,
        in_progress=in_progress,
        in_repeated_error_state=cc_pair.in_repeated_error_state,
        last_finished_status=(
            latest_finished_index_attempt.status
            if latest_finished_index_attempt
            else None
        ),
        last_status=latest_index_attempt.status if latest_index_attempt else None,
        last_success=cc_pair.last_successful_index_time,
        docs_indexed=document_cnt,
        latest_index_attempt_docs_indexed=(
            latest_index_attempt.total_docs_indexed if latest_index_attempt else None
        ),
    )


def _apply_connector_status_filters(
    statuses: list[ConnectorIndexingStatusLite],
    access_type_filters: list[AccessType],
    last_status_filters: list[IndexingStatus],
    docs_count_operator: DocsCountOperator | None,
    docs_count_value: int | None,
    name_filter: str | None,
) -> list[ConnectorIndexingStatusLite]:
    """Apply filters to a list of ConnectorIndexingStatusLite objects"""
    filtered_statuses: list[ConnectorIndexingStatusLite] = []

    for status in statuses:
        # Filter by access type
        if access_type_filters and status.access_type not in access_type_filters:
            continue

        # Filter by last status
        if last_status_filters and status.last_status not in last_status_filters:
            continue

        # Filter by document count
        if docs_count_operator and docs_count_value is not None:
            if docs_count_operator == DocsCountOperator.GREATER_THAN and not (
                status.docs_indexed > docs_count_value
            ):
                continue
            elif docs_count_operator == DocsCountOperator.LESS_THAN and not (
                status.docs_indexed < docs_count_value
            ):
                continue
            elif (
                docs_count_operator == DocsCountOperator.EQUAL_TO
                and status.docs_indexed != docs_count_value
            ):
                continue

        # Filter by name
        if status.name:
            if name_filter and name_filter.lower() not in status.name.lower():
                continue
        else:
            if name_filter:
                continue

        filtered_statuses.append(status)

    return filtered_statuses


def _apply_federated_connector_status_filters(
    statuses: list[FederatedConnectorStatus],
    name_filter: str | None,
) -> list[FederatedConnectorStatus]:
    filtered_statuses: list[FederatedConnectorStatus] = []

    for status in statuses:
        if name_filter and name_filter.lower() not in status.name.lower():
            continue

        filtered_statuses.append(status)

    return filtered_statuses


def _validate_connector_allowed(source: DocumentSource) -> None:
    valid_connectors = [
        x for x in ENABLED_CONNECTOR_TYPES.replace("_", "").split(",") if x
    ]
    if not valid_connectors:
        return
    for connector_type in valid_connectors:
        if source.value.lower().replace("_", "") == connector_type:
            return

    raise ValueError(
        "This connector type has been disabled by your system admin. "
        "Please contact them to get it enabled if you wish to use it."
    )


@router.post("/admin/connector")
def create_connector_from_model(
    connector_data: ConnectorUpdateRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> ObjectCreationIdResponse:
    tenant_id = get_current_tenant_id()

    try:
        _validate_connector_allowed(connector_data.source)

        fetch_ee_implementation_or_noop(
            "onyx.db.user_group", "validate_object_creation_for_user", None
        )(
            db_session=db_session,
            user=user,
            target_group_ids=connector_data.groups,
            object_is_public=connector_data.access_type == AccessType.PUBLIC,
            object_is_perm_sync=connector_data.access_type == AccessType.SYNC,
            object_is_new=True,
        )
        connector_base = connector_data.to_connector_base()
        connector_response = create_connector(
            db_session=db_session,
            connector_data=connector_base,
        )

        create_milestone_and_report(
            user=user,
            distinct_id=user.email if user else tenant_id or "N/A",
            event_type=MilestoneRecordType.CREATED_CONNECTOR,
            properties=None,
            db_session=db_session,
        )

        return connector_response
    except ValueError as e:
        logger.error(f"Error creating connector: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/connector-with-mock-credential")
def create_connector_with_mock_credential(
    connector_data: ConnectorUpdateRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    tenant_id = get_current_tenant_id()

    fetch_ee_implementation_or_noop(
        "onyx.db.user_group", "validate_object_creation_for_user", None
    )(
        db_session=db_session,
        user=user,
        target_group_ids=connector_data.groups,
        object_is_public=connector_data.access_type == AccessType.PUBLIC,
        object_is_perm_sync=connector_data.access_type == AccessType.SYNC,
    )
    try:
        _validate_connector_allowed(connector_data.source)
        connector_response = create_connector(
            db_session=db_session,
            connector_data=connector_data,
        )

        mock_credential = CredentialBase(
            credential_json={},
            admin_public=True,
            source=connector_data.source,
        )
        credential = create_credential(
            credential_data=mock_credential,
            user=user,
            db_session=db_session,
        )

        # Store the created connector and credential IDs
        connector_id = cast(int, connector_response.id)
        credential_id = credential.id

        validate_ccpair_for_user(
            connector_id=connector_id,
            credential_id=credential_id,
            access_type=connector_data.access_type,
            db_session=db_session,
        )
        response = add_credential_to_connector(
            db_session=db_session,
            user=user,
            connector_id=connector_id,
            credential_id=credential_id,
            access_type=connector_data.access_type,
            cc_pair_name=connector_data.name,
            groups=connector_data.groups,
        )

        # trigger indexing immediately
        client_app.send_task(
            OnyxCeleryTask.CHECK_FOR_INDEXING,
            priority=OnyxCeleryPriority.HIGH,
            kwargs={"tenant_id": tenant_id},
        )

        logger.info(
            f"create_connector_with_mock_credential - running check_for_indexing: "
            f"cc_pair={response.data}"
        )

        create_milestone_and_report(
            user=user,
            distinct_id=user.email if user else tenant_id or "N/A",
            event_type=MilestoneRecordType.CREATED_CONNECTOR,
            properties=None,
            db_session=db_session,
        )
        return response

    except ConnectorValidationError as e:
        raise HTTPException(
            status_code=400, detail="Connector validation error: " + str(e)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/admin/connector/{connector_id}")
def update_connector_from_model(
    connector_id: int,
    connector_data: ConnectorUpdateRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> ConnectorSnapshot | StatusResponse[int]:
    cc_pair = fetch_connector_credential_pair_for_connector(db_session, connector_id)
    try:
        _validate_connector_allowed(connector_data.source)
        fetch_ee_implementation_or_noop(
            "onyx.db.user_group", "validate_object_creation_for_user", None
        )(
            db_session=db_session,
            user=user,
            target_group_ids=connector_data.groups,
            object_is_public=connector_data.access_type == AccessType.PUBLIC,
            object_is_perm_sync=connector_data.access_type == AccessType.SYNC,
            object_is_owned_by_user=cc_pair and user and cc_pair.creator_id == user.id,
        )
        connector_base = connector_data.to_connector_base()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    updated_connector = update_connector(connector_id, connector_base, db_session)
    if updated_connector is None:
        raise HTTPException(
            status_code=404, detail=f"Connector {connector_id} does not exist"
        )

    return ConnectorSnapshot(
        id=updated_connector.id,
        name=updated_connector.name,
        source=updated_connector.source,
        input_type=updated_connector.input_type,
        connector_specific_config=updated_connector.connector_specific_config,
        refresh_freq=updated_connector.refresh_freq,
        prune_freq=updated_connector.prune_freq,
        credential_ids=[
            association.credential.id for association in updated_connector.credentials
        ],
        indexing_start=updated_connector.indexing_start,
        time_created=updated_connector.time_created,
        time_updated=updated_connector.time_updated,
    )


@router.delete("/admin/connector/{connector_id}", response_model=StatusResponse[int])
def delete_connector_by_id(
    connector_id: int,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    try:
        with db_session.begin():
            return delete_connector(
                db_session=db_session,
                connector_id=connector_id,
            )
    except AssertionError:
        raise HTTPException(status_code=400, detail="Connector is not deletable")


@router.post("/admin/connector/run-once")
def connector_run_once(
    run_info: RunConnectorRequest,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    """Used to trigger indexing on a set of cc_pairs associated with a
    single connector."""
    tenant_id = get_current_tenant_id()

    connector_id = run_info.connector_id
    specified_credential_ids = run_info.credential_ids

    try:
        possible_credential_ids = get_connector_credential_ids(
            run_info.connector_id, db_session
        )
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f"Connector by id {connector_id} does not exist.",
        )

    if not specified_credential_ids:
        credential_ids = possible_credential_ids
    else:
        if set(specified_credential_ids).issubset(set(possible_credential_ids)):
            credential_ids = specified_credential_ids
        else:
            raise HTTPException(
                status_code=400,
                detail="Not all specified credentials are associated with connector",
            )

    if not credential_ids:
        raise HTTPException(
            status_code=400,
            detail="Connector has no valid credentials, cannot create index attempts.",
        )
    try:
        num_triggers = trigger_indexing_for_cc_pair(
            credential_ids,
            connector_id,
            run_info.from_beginning,
            tenant_id,
            db_session,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("connector_run_once - running check_for_indexing")

    msg = f"Marked {num_triggers} index attempts with indexing triggers."
    return StatusResponse(
        success=True,
        message=msg,
        data=num_triggers,
    )


"""Endpoints for basic users"""


@router.get("/connector/gmail/authorize/{credential_id}")
def gmail_auth(
    response: Response, credential_id: str, _: User = Depends(current_user)
) -> AuthUrl:
    # set a cookie that we can read in the callback (used for `verify_csrf`)
    response.set_cookie(
        key=_GMAIL_CREDENTIAL_ID_COOKIE_NAME,
        value=credential_id,
        httponly=True,
        max_age=600,
    )
    return AuthUrl(auth_url=get_auth_url(int(credential_id), DocumentSource.GMAIL))


@router.get("/connector/google-drive/authorize/{credential_id}")
def google_drive_auth(
    response: Response, credential_id: str, _: User = Depends(current_user)
) -> AuthUrl:
    # set a cookie that we can read in the callback (used for `verify_csrf`)
    response.set_cookie(
        key=_GOOGLE_DRIVE_CREDENTIAL_ID_COOKIE_NAME,
        value=credential_id,
        httponly=True,
        max_age=600,
    )
    return AuthUrl(
        auth_url=get_auth_url(int(credential_id), DocumentSource.GOOGLE_DRIVE)
    )


@router.get("/connector/gmail/callback")
def gmail_callback(
    request: Request,
    callback: GmailCallback = Depends(),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    credential_id_cookie = request.cookies.get(_GMAIL_CREDENTIAL_ID_COOKIE_NAME)
    if credential_id_cookie is None or not credential_id_cookie.isdigit():
        raise HTTPException(
            status_code=401, detail="Request did not pass CSRF verification."
        )
    credential_id = int(credential_id_cookie)
    verify_csrf(credential_id, callback.state)
    credentials: Credentials | None = update_credential_access_tokens(
        callback.code,
        credential_id,
        user,
        db_session,
        DocumentSource.GMAIL,
        GoogleOAuthAuthenticationMethod.UPLOADED,
    )
    if credentials is None:
        raise HTTPException(
            status_code=500, detail="Unable to fetch Gmail access tokens"
        )

    return StatusResponse(success=True, message="Updated Gmail access tokens")


@router.get("/connector/google-drive/callback")
def google_drive_callback(
    request: Request,
    callback: GDriveCallback = Depends(),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    credential_id_cookie = request.cookies.get(_GOOGLE_DRIVE_CREDENTIAL_ID_COOKIE_NAME)
    if credential_id_cookie is None or not credential_id_cookie.isdigit():
        raise HTTPException(
            status_code=401, detail="Request did not pass CSRF verification."
        )
    credential_id = int(credential_id_cookie)
    verify_csrf(credential_id, callback.state)

    credentials: Credentials | None = update_credential_access_tokens(
        callback.code,
        credential_id,
        user,
        db_session,
        DocumentSource.GOOGLE_DRIVE,
        GoogleOAuthAuthenticationMethod.UPLOADED,
    )
    if credentials is None:
        raise HTTPException(
            status_code=500, detail="Unable to fetch Google Drive access tokens"
        )

    return StatusResponse(success=True, message="Updated Google Drive access tokens")


@router.get("/connector")
def get_connectors(
    _: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[ConnectorSnapshot]:
    connectors = fetch_connectors(db_session)
    return [
        ConnectorSnapshot.from_connector_db_model(connector)
        for connector in connectors
        # don't include INGESTION_API, as it's not a "real"
        # connector like those created by the user
        if connector.source != DocumentSource.INGESTION_API
    ]


@router.get("/connector/{connector_id}")
def get_connector_by_id(
    connector_id: int,
    _: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ConnectorSnapshot | StatusResponse[int]:
    connector = fetch_connector_by_id(connector_id, db_session)
    if connector is None:
        raise HTTPException(
            status_code=404, detail=f"Connector {connector_id} does not exist"
        )

    return ConnectorSnapshot(
        id=connector.id,
        name=connector.name,
        source=connector.source,
        indexing_start=connector.indexing_start,
        input_type=connector.input_type,
        connector_specific_config=connector.connector_specific_config,
        refresh_freq=connector.refresh_freq,
        prune_freq=connector.prune_freq,
        credential_ids=[
            association.credential.id for association in connector.credentials
        ],
        time_created=connector.time_created,
        time_updated=connector.time_updated,
    )


class BasicCCPairInfo(BaseModel):
    has_successful_run: bool
    source: DocumentSource


@router.get("/connector-status")
def get_basic_connector_indexing_status(
    user: User = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> list[BasicCCPairInfo]:
    cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        eager_load_connector=True,
        get_editable=False,
        user=user,
    )
    return [
        BasicCCPairInfo(
            has_successful_run=cc_pair.last_successful_index_time is not None,
            source=cc_pair.connector.source,
        )
        for cc_pair in cc_pairs
        if cc_pair.connector.source != DocumentSource.INGESTION_API
    ]


def trigger_indexing_for_cc_pair(
    specified_credential_ids: list[int],
    connector_id: int,
    from_beginning: bool,
    tenant_id: str,
    db_session: Session,
    is_user_file: bool = False,
) -> int:
    try:
        possible_credential_ids = get_connector_credential_ids(connector_id, db_session)
    except ValueError as e:
        raise ValueError(f"Connector by id {connector_id} does not exist: {str(e)}")

    if not specified_credential_ids:
        credential_ids = possible_credential_ids
    else:
        if set(specified_credential_ids).issubset(set(possible_credential_ids)):
            credential_ids = specified_credential_ids
        else:
            raise ValueError(
                "Not all specified credentials are associated with connector"
            )

    if not credential_ids:
        raise ValueError(
            "Connector has no valid credentials, cannot create index attempts."
        )

    # Prevents index attempts for cc pairs that already have an index attempt currently running
    skipped_credentials = [
        credential_id
        for credential_id in credential_ids
        if get_index_attempts_for_cc_pair(
            cc_pair_identifier=ConnectorCredentialPairIdentifier(
                connector_id=connector_id,
                credential_id=credential_id,
            ),
            only_current=True,
            db_session=db_session,
            disinclude_finished=True,
        )
    ]

    connector_credential_pairs = [
        get_connector_credential_pair(
            db_session=db_session,
            connector_id=connector_id,
            credential_id=credential_id,
        )
        for credential_id in credential_ids
        if credential_id not in skipped_credentials
    ]

    num_triggers = 0
    for cc_pair in connector_credential_pairs:
        if cc_pair is not None:
            indexing_mode = IndexingMode.UPDATE
            if from_beginning:
                indexing_mode = IndexingMode.REINDEX

            mark_ccpair_with_indexing_trigger(cc_pair.id, indexing_mode, db_session)
            num_triggers += 1

            logger.info(
                f"connector_run_once - marking cc_pair with indexing trigger: "
                f"connector={connector_id} "
                f"cc_pair={cc_pair.id} "
                f"indexing_trigger={indexing_mode}"
            )

    # run the beat task to pick up the triggers immediately
    priority = OnyxCeleryPriority.HIGHEST if is_user_file else OnyxCeleryPriority.HIGH
    logger.info(f"Sending indexing check task with priority {priority}")
    client_app.send_task(
        OnyxCeleryTask.CHECK_FOR_INDEXING,
        priority=priority,
        kwargs={"tenant_id": tenant_id},
    )

    return num_triggers
