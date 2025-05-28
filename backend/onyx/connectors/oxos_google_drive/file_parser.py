import os
import json
from collections.abc import Iterator
from datetime import datetime
from functools import partial
from typing import Any, Optional, List, Dict

from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore
from concurrent.futures import ThreadPoolExecutor, as_completed

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD
from onyx.configs.app_configs import MAX_FILE_SIZE_BYTES
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError, CredentialExpiredError, InsufficientPermissionsError
from onyx.connectors.google_drive.doc_conversion import build_slim_document, convert_drive_item_to_document
from onyx.connectors.google_drive.file_retrieval import (
    get_all_files_for_oauth,
    get_all_files_in_my_drive_and_shared,
    get_files_in_shared_drive,
    get_root_folder_id,
    generate_time_range_filter,
)
from onyx.connectors.google_drive.google_docs import read_document, write_document, insert_text, delete_text_range
from onyx.connectors.google_drive.google_sheets import read_spreadsheet
from onyx.connectors.google_drive.models import GoogleDriveFileType, DriveRetrievalStage, RetrievedDriveFile
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import (
    execute_paginated_retrieval,
    execute_single_retrieval,
    _execute_single_retrieval,
    get_file_owners,
    GoogleFields,
)
from onyx.connectors.google_utils.resources import get_admin_service, get_drive_service, get_google_docs_service, get_sheets_service, GoogleDriveService
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
    GoogleOAuthAuthenticationMethod,
    MISSING_SCOPES_ERROR_STR,
    ONYX_SCOPE_INSTRUCTIONS,
    SLIM_BATCH_SIZE,
    USER_FIELDS,
)
from onyx.connectors.models import Document, ConnectorMissingCredentialError
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

# Constants
LARGE_BATCH_SIZE = 20


# export type FileEntry = {
#   id: string;
#   name: string;
#   type: 'file' | 'folder';
#   fileType?: 'document' | 'spreadsheet';
#   children?: FileEntry[];
#   url?: string;
#   docId?: string;
# };

# export const defaultSidebarFiles: FileEntry[] = [
#   {
#     id: 'dhf-file',
#     name: 'DHF-008 - MC2-OXO Design History File Checklist_D-signed',
#     type: 'file',
#     fileType: 'spreadsheet',
#     url: 'https://docs.google.com/spreadsheets/d/1ChieZhtyALESO4r-PDxfZsT0jYJHmunuyoYu8Lpo1cs/edit?gid=25002498#gid=25002498',
#     docId: '1ChieZhtyALESO4r-PDxfZsT0jYJHmunuyoYu8Lpo1cs',
#   },
#   {


class OxosGoogleDriveConnector():
    def __init__(
        self,
        include_shared_drives: bool = True,
        include_my_drives: bool = True,
        include_files_shared_with_me: bool = True,
        shared_drive_ids: Optional[List[str]] = None,
        folder_ids: Optional[List[str]] = None,
    ) -> None:
        """
        Initialize the OXOS Google Drive Connector.
        
        Args:
            include_shared_drives: Whether to include shared drives in the retrieval
            include_my_drives: Whether to include the user's own drives
            include_files_shared_with_me: Whether to include files shared with the user
            shared_drive_ids: Optional list of specific shared drive IDs to include
            folder_ids: Optional list of specific folder IDs to include
        """
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
        """Get the Google credentials."""
        return self._creds

    @property
    def primary_admin_email(self) -> str:
        """Get the primary admin email."""
        return self._primary_admin_email
    
    def set_allow_images(self, value: bool) -> None:
        """Set whether to allow images in document processing."""
        self._allow_images = value

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        """Load credentials for Google Drive access.
        
        Args:
            credentials: Dictionary containing credential information
        """
        """Load credentials from environment variables with OXOS_ prefix."""
        self._primary_admin_email = os.getenv("OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL")
        if not self._primary_admin_email:
            raise ValueError("Missing required environment variable: OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL")

        credentials = {
            DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: os.getenv("OXOS_GOOGLE_SERVICE_ACCOUNT_JSON"),
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY: self._primary_admin_email,
        }

        # get_google_creds returns a tuple (creds, new_creds_dict)
        creds, _ = get_google_creds(credentials, DocumentSource.GOOGLE_DRIVE)
        self._creds = creds

    def validate_connector_settings(self) -> None:
        """Validate the connector settings and credentials."""
        if self._creds is None:
            raise ConnectorMissingCredentialError(
                "Google Drive credentials not loaded."
            )

        if self._primary_admin_email is None:
            raise ConnectorValidationError(
                "Primary admin email not found in credentials. "
                "Ensure DB_CREDENTIALS_PRIMARY_ADMIN_KEY is set."
            )

        try:
            drive_service = get_drive_service(self._creds, self._primary_admin_email)
            drive_service.files().list(pageSize=1, fields="files(id)").execute()

            if isinstance(self._creds, ServiceAccountCredentials):
                # default is ~17mins of retries, don't do that here since this is called from
                # the UI
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
            # Check for scope-related hints from the error message
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise InsufficientPermissionsError(
                    "Google Drive credentials are missing required scopes. "
                    f"{ONYX_SCOPE_INSTRUCTIONS}"
                )
            raise ConnectorValidationError(
                f"Unexpected error during Google Drive validation: {e}"
            )
    
    def load_from_state(self) -> Dict[str, Any]:
        """Load and process documents from the spreadsheet state.
        
        This method reads a Google Spreadsheet containing document links,
        retrieves those documents, and yields them in batches.
        
        Returns:
            Generator yielding batches of documents
        """
        documents = []
        try:
            if self._creds is None:
                raise ConnectorMissingCredentialError("Google Drive credentials not loaded.")
            
            # Get the spreadsheet and drive services
            sheets_service = get_sheets_service(self._creds, self._primary_admin_email)
            drive_service = get_drive_service(self._creds, self._primary_admin_email)
            
            # Fetch the spreadsheet with document links from environment variable
            spreadsheet_id = os.getenv("OXOS_GOOGLE_SPREADSHEET_ID")
            if not spreadsheet_id:
                raise ValueError("OXOS_GOOGLE_SPREADSHEET_ID environment variable not set")
            
            # First, get the spreadsheet metadata to find available sheets
            spreadsheet_metadata = sheets_service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            
            # Get the first sheet name
            if not spreadsheet_metadata.get('sheets'):
                raise ValueError(f"No sheets found in spreadsheet {spreadsheet_id}")
                
            first_sheet_name = spreadsheet_metadata['sheets'][1]['properties']['title']
            logger.info(f"Using sheet: {first_sheet_name}")
            
            # Now get the values from the first sheet
            result = read_spreadsheet(
                self.creds,
                self.primary_admin_email,
                # Spreadsheet ID now loaded from environment variable for configurability
                spreadsheet_id=spreadsheet_id,
                sheet_name="Design History FIle Checklist"
            )
            values = result.get("values", [])

            # add the original spreadsheet
            documents.append({
                "id": spreadsheet_id,
                "name": spreadsheet_metadata['properties']['title'],
                "type": "file",
                "fileType": "spreadsheet",
                "url": spreadsheet_metadata['spreadsheetUrl'],
                "docId": spreadsheet_id,
            })

            # first doc to process is the spreadsheet itself
            file = _execute_single_retrieval(
                retrieval_function=drive_service.files().get,
                fileId=spreadsheet_id,
                fields="id,name,mimeType,owners,modifiedTime,createdTime,webViewLink,size",
                supportsAllDrives=True
            )            
            # Process rows in the spreadsheet
            for row in values:
                if len(row) >= 3:
                    group = row[0]
                    link_cell = row[2]
                    
                    # Extract document URL from the cell
                    doc_url = None
                    if isinstance(link_cell, dict) and "hyperlink" in link_cell:
                        doc_url = link_cell["hyperlink"]
                    elif isinstance(link_cell, str) and (link_cell.startswith("http") or "docs.google.com" in link_cell):
                        doc_url = link_cell
                        
                    if not doc_url:
                        continue
                        
                    # Extract document ID from URL
                    try:
                        # Handle different Google Doc URL formats
                        if "/d/" in doc_url:
                            doc_id = doc_url.split("/d/")[1].split("/")[0]
                        else:
                            doc_id = doc_url.split("/")[-2]  # Google Doc URLs end with /edit
                    except IndexError:
                        logger.error(f"Invalid document URL: {doc_url} for row: {row}")
                        continue
                    
                    # Get the drive item using the service
                    try:
                        # Use execute_single_retrieval for better error handling
                        file = _execute_single_retrieval(
                            retrieval_function=drive_service.files().get,
                            fileId=doc_id,
                            fields="id,name,mimeType,owners,modifiedTime,createdTime,webViewLink,size",
                            supportsAllDrives=True
                        )
                        
                        documents.append({
                            "id": doc_id,
                            "name": file['name'],
                            "type": "file",
                            "fileType": "document" if "document" in file["webViewLink"] else "spreadsheet",
                            "url": file['webViewLink'],
                            "docId": doc_id,
                        })
                                
                    except HttpError as e:
                        logger.error(f"Error fetching file {row[1]}: {str(e)}")
                        continue
            
            return documents
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            logger.error(f"Error in load_from_state: {str(e)}")
            raise e

def main():
    """Run the OxosGoogleDriveConnector to load and process linked documents."""
    try:
        # Load service account credentials from environment variable
        service_account_json = os.getenv("OXOS_GOOGLE_SERVICE_ACCOUNT_JSON")
        if not service_account_json:
            raise ValueError("OXOS_GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")
            
        primary_admin_email = os.getenv("OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL")
        if not primary_admin_email:
            raise ValueError("OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL environment variable not set")
            
        spreadsheet_id = os.getenv("OXOS_GOOGLE_SPREADSHEET_ID")
        if not spreadsheet_id:
            print("Warning: OXOS_GOOGLE_SPREADSHEET_ID not set, using default")

        # Initialize and configure connector
        connector = OxosGoogleDriveConnector(
            include_shared_drives=True,
            include_my_drives=True,
            include_files_shared_with_me=True
        )
        
        connector.load_credentials({
            DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: service_account_json,
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY: primary_admin_email,
        })
        
        documents = connector.load_from_state()

        # write out the documents to a json file
        with open("documents.json", "w") as f:
            json.dump(documents, f)
        
    except Exception as e:
        print(f"Error running connector: {str(e)}")
        raise e

if __name__ == "__main__":
    """PYTHONPATH=/Users/steven/Desktop/repos/onyx/onyx/backend python3 /Users/steven/Desktop/repos/onyx/onyx/backend/onyx/connectors/oxos_google_drive/file_parser.py"""
    main()
