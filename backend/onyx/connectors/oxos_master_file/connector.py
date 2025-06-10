import os
from typing import Any, List, Optional

from google.oauth2.service_account import (
    Credentials as ServiceAccountCredentials,  # type: ignore
)
from googleapiclient.errors import HttpError  # type: ignore

from onyx.configs.app_configs import (
    GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD,
    INDEX_BATCH_SIZE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.google_drive.doc_conversion import (
    build_slim_document,
    convert_drive_item_to_document,
)
from onyx.connectors.google_drive.file_retrieval import (
    get_all_files_for_oauth,
    get_files_in_shared_drive,
    get_root_folder_id,
)
from onyx.connectors.google_drive.google_sheets import read_spreadsheet
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import _execute_single_retrieval
from onyx.connectors.google_utils.resources import get_drive_service
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    MISSING_SCOPES_ERROR_STR,
    ONYX_SCOPE_INSTRUCTIONS,
    SLIM_BATCH_SIZE,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

LARGE_BATCH_SIZE = 20


class OxosMasterFileConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        include_shared_drives: bool = True,
        include_my_drives: bool = True,
        include_files_shared_with_me: bool = True,
        shared_drive_ids: Optional[List[str]] = None,
        folder_ids: Optional[List[str]] = None,
    ) -> None:
        self._include_shared_drives = include_shared_drives
        self._include_my_drives = include_my_drives
        self._include_files_shared_with_me = include_files_shared_with_me
        self._shared_drive_ids = shared_drive_ids or []
        self._folder_ids = folder_ids or []
        self._creds = None
        self._primary_admin_email = None
        self._allow_images = False
        self._size_threshold = GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD

    @property
    def creds(self) -> Any:
        return self._creds

    @property
    def primary_admin_email(self) -> str:
        if self._primary_admin_email is None:
            raise ValueError("Primary admin email not set")
        return self._primary_admin_email

    def set_allow_images(self, value: bool) -> None:
        self._allow_images = value

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        self._primary_admin_email = os.getenv("OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL")
        if not self._primary_admin_email:
            raise ValueError("Missing required environment variable: OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL")

        credentials = {
            DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: os.getenv("OXOS_GOOGLE_SERVICE_ACCOUNT_JSON"),
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY: self._primary_admin_email,
        }

        creds, _ = get_google_creds(credentials, DocumentSource.GOOGLE_DRIVE)
        self._creds = creds

    def validate_connector_settings(self) -> None:
        if self._creds is None:
            raise ConnectorMissingCredentialError(
                "Google Drive credentials not loaded."
            )

        if self._primary_admin_email is None:
            raise ConnectorValidationError(
                "Primary admin email not found in credentials. "
                "Ensure OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL is set."
            )

        try:
            drive_service = get_drive_service(self._creds, self._primary_admin_email)
            drive_service.files().list(pageSize=1, fields="files(id)").execute()

            if isinstance(self._creds, ServiceAccountCredentials):
                retry_builder(tries=3, delay=0.1)(get_root_folder_id)(drive_service)

        except HttpError as e:
            status_code = e.resp.status if e.resp else None
            if status_code == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Google Drive credentials (401)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Google Drive app lacks required permissions (403). "
                    "Please ensure the necessary scopes are granted and Drive "
                    "apps are enabled."
                )
            else:
                raise ConnectorValidationError(
                    f"Unexpected Google Drive error (status={status_code}): {e}"
                )

        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise InsufficientPermissionsError(
                    "Google Drive credentials are missing required scopes. "
                    f"{ONYX_SCOPE_INSTRUCTIONS}"
                )
            raise ConnectorValidationError(
                f"Unexpected error during Google Drive validation: {e}"
            )

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        yield from self.load_from_state()

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateSlimDocumentOutput:
        if self._creds is None:
            raise ConnectorMissingCredentialError("Google Drive credentials not loaded.")

        drive_service = get_drive_service(self._creds, self._primary_admin_email)
        slim_batch = []

        try:
            if self._include_shared_drives and self._shared_drive_ids:
                for drive_id in self._shared_drive_ids:
                    for file in get_files_in_shared_drive(
                        service=drive_service,
                        drive_id=drive_id,
                        is_slim=True,
                        start=start,
                        end=end
                    ):
                        if doc := build_slim_document(file):
                            slim_batch.append(doc)
                            if len(slim_batch) >= SLIM_BATCH_SIZE:
                                yield slim_batch
                                slim_batch = []

            for file in get_all_files_for_oauth(
                service=drive_service,
                include_files_shared_with_me=self._include_files_shared_with_me,
                include_my_drives=self._include_my_drives,
                include_shared_drives=self._include_shared_drives,
                is_slim=True,
                start=start,
                end=end
            ):
                if doc := build_slim_document(file):
                    slim_batch.append(doc)
                    if len(slim_batch) >= SLIM_BATCH_SIZE:
                        yield slim_batch
                        slim_batch = []

            if slim_batch:
                yield slim_batch

        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    def load_from_state(self) -> GenerateDocumentsOutput:
        try:
            if self._creds is None:
                raise ConnectorMissingCredentialError("Google Drive credentials not loaded.")

            drive_service = get_drive_service(self._creds, self._primary_admin_email)

            # TODO: Make this configurable
            spreadsheet_id = "1zUx2p5QgIqAQQY3h0txOHqhJQbReL3YTx5EsIg5wdqw"

            result = read_spreadsheet(
                self.creds,
                self.primary_admin_email,
                spreadsheet_id=spreadsheet_id,
                sheet_name="Master Document List"
            )
            values = result.get("values", [])

            file = _execute_single_retrieval(
                retrieval_function=drive_service.files().get,
                fileId=spreadsheet_id,
                fields="id,name,mimeType,owners,modifiedTime,createdTime,webViewLink,size",
                supportsAllDrives=True
            )
            docs_to_process = [convert_drive_item_to_document(self._creds, self._allow_images, self._size_threshold, [self.primary_admin_email], file, sheet_extract_hyperlinks=False)]
            for row in values:
                if len(row) >= 3:
                    rev_cell = row[1]
                    effective_date = row[2] if len(row) > 2 else ""

                    doc_url = None
                    if isinstance(rev_cell, dict) and "hyperlink" in rev_cell:
                        doc_url = rev_cell["hyperlink"]
                    elif isinstance(rev_cell, str) and (rev_cell.startswith("http") or "docs.google.com" in rev_cell):
                        doc_url = rev_cell

                    if not doc_url:
                        continue

                    try:
                        if "/d/" in doc_url:
                            doc_id = doc_url.split("/d/")[1].split("/")[0]
                        else:
                            doc_id = doc_url.split("/")[-2]
                    except IndexError:
                        logger.error(f"Invalid document URL: {doc_url} for row: {row}")
                        continue

                    try:
                        file = _execute_single_retrieval(
                            retrieval_function=drive_service.files().get,
                            fileId=doc_id,
                            fields="id,name,mimeType,owners,modifiedTime,createdTime,webViewLink,size",
                            supportsAllDrives=True
                        )

                        file["metadata"] = {
                            "rev": rev_cell,
                            "effective_date": effective_date,
                        }
                        doc = convert_drive_item_to_document(self._creds, self._allow_images, self._size_threshold, [self.primary_admin_email], file)
                        if doc:
                            docs_to_process.append(doc)

                            if len(docs_to_process) >= INDEX_BATCH_SIZE:
                                yield docs_to_process
                                docs_to_process = []

                    except HttpError as e:
                        logger.error(f"Error fetching file {doc_id}: {str(e)}")
                        continue

            if docs_to_process:
                yield docs_to_process

        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            logger.error(f"Error in load_from_state: {str(e)}")
            raise e


def main():
    """Run the OxosMasterFileConnector to load and process linked documents.
    This connector ingests Oxos documents from their master QSR (quality system records)
    which is essentially all of their docs stored in their QMS.
    """
    try:
        # Load service account credentials from environment variable
        service_account_json = os.getenv("OXOS_GOOGLE_SERVICE_ACCOUNT_JSON")
        if not service_account_json:
            raise ValueError("OXOS_GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")

        primary_admin_email = os.getenv("OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL")
        if not primary_admin_email:
            raise ValueError("OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL environment variable not set")

        # Initialize and configure connector
        connector = OxosMasterFileConnector(
            include_shared_drives=True,
            include_my_drives=True,
            include_files_shared_with_me=True
        )

        connector.load_credentials({
            DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: service_account_json,
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY: primary_admin_email,
        })

        # Validate connector settings
        connector.validate_connector_settings()

        print("\n=== Processing linked documents from spreadsheet ===")
        print("-" * 50)

        # Option 1: Load documents from spreadsheet
        print("\nOption 1: Loading documents from spreadsheet...")
        doc_count = 0
        for docs in connector.load_from_state():
            for doc in docs:
                doc_count += 1
                print(f"\nTitle: {doc.semantic_identifier}")
                if doc.sections and len(doc.sections) > 0:
                    preview = doc.sections[0].text[:100] + "..." if len(doc.sections[0].text) > 100 else doc.sections[0].text
                    print(f"Content Preview: {preview}")
                print("-" * 50)
        print(f"\nLoaded {doc_count} documents from spreadsheet")

    except Exception as e:
        print(f"Error running connector: {str(e)}")
        raise e

if __name__ == "__main__":
    main()
