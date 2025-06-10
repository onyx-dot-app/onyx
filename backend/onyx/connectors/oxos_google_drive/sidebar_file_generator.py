import os
import json
import argparse
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.resources import get_drive_service
from onyx.connectors.google_utils.google_utils import execute_single_retrieval, _execute_single_retrieval
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    MISSING_SCOPES_ERROR_STR,
    ONYX_SCOPE_INSTRUCTIONS,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

class GoogleDriveSidebarGenerator:
    def __init__(self):
        """
        Initialize the Google Drive Sidebar Generator.
        """
        self._creds = None
        self._primary_admin_email = None
        self._drive_service = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        """
        Load credentials for Google Drive access.
        
        Args:
            credentials: Dictionary containing credential information
        """
        service_account_json = credentials.get(DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY)
        self._primary_admin_email = credentials.get(DB_CREDENTIALS_PRIMARY_ADMIN_KEY)
        
        if not service_account_json:
            raise ValueError("Service account JSON is required")
        
        if not self._primary_admin_email:
            raise ValueError("Primary admin email is required")
        
        # Load service account credentials
        try:
            service_account_info = json.loads(service_account_json)
            self._creds = ServiceAccountCredentials.from_service_account_info(
                service_account_info,
                scopes=['https://www.googleapis.com/auth/drive.readonly'],
                subject=self._primary_admin_email
            )
            # Initialize the drive service
            self._drive_service = get_drive_service(self._creds)
        except Exception as e:
            logger.error(f"Error loading credentials: {str(e)}")
            raise e

    def get_files_from_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """
        Get all files from a specific Google Drive folder.
        
        Args:
            folder_id: The ID of the Google Drive folder
            
        Returns:
            List of file objects with metadata
        """
        if not self._drive_service:
            raise ValueError("Drive service not initialized. Load credentials first.")
        
        try:
            # Get folder details first
            folder = _execute_single_retrieval(
                retrieval_function=self._drive_service.files().get,
                fileId=folder_id,
                fields="id,name,mimeType",
                supportsAllDrives=True
            )
            
            # Check if it's actually a folder
            if folder.get('mimeType') != 'application/vnd.google-apps.folder':
                raise ValueError(f"The provided ID {folder_id} is not a folder")
            
            # Query for all files in the folder
            query = f"'{folder_id}' in parents"
            files = []
            page_token = None
            
            while True:
                response = self._drive_service.files().list(
                    q=query,
                    spaces='drive',
                    fields="nextPageToken, files(id, name, mimeType, webViewLink)",
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()
                
                items = response.get('files', [])
                
                for item in items:
                    file_type = 'folder' if item['mimeType'] == 'application/vnd.google-apps.folder' else 'file'
                    file_entry = {
                        "id": item['id'],
                        "name": item['name'],
                        "type": file_type,
                    }
                    
                    # Add file-specific properties
                    if file_type == 'file':
                        if item['mimeType'] == 'application/vnd.google-apps.document':
                            file_entry["fileType"] = "document"
                        elif item['mimeType'] == 'application/vnd.google-apps.spreadsheet':
                            file_entry["fileType"] = "spreadsheet"
                        elif item['mimeType'] == 'application/vnd.google-apps.presentation':
                            file_entry["fileType"] = "presentation"
                        else:
                            file_entry["fileType"] = "other"
                        
                        file_entry["url"] = item.get('webViewLink', '')
                        file_entry["docId"] = item['id']
                    
                    # If it's a folder, recursively get its children
                    if file_type == 'folder':
                        file_entry["children"] = self.get_files_from_folder(item['id'])
                    
                    files.append(file_entry)
                
                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            
            return files
            
        except HttpError as e:
            logger.error(f"Error fetching files from folder {folder_id}: {str(e)}")
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise e

def main():
    """
    Run the GoogleDriveSidebarGenerator to generate a JSON file of all files in the specified folder.
    """
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Generate a JSON file of all files in a specified Google Drive folder.')
    parser.add_argument('--folder-id', type=str, help='The ID of the Google Drive folder to process')
    args = parser.parse_args()
    
    try:
        # Load service account credentials from environment variable
        service_account_json = os.getenv("OXOS_GOOGLE_SERVICE_ACCOUNT_JSON")
        if not service_account_json:
            raise ValueError("OXOS_GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")
            
        primary_admin_email = os.getenv("OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL")
        if not primary_admin_email:
            raise ValueError("OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL environment variable not set")
        
        # Get the folder ID from command line argument, environment variable, or use the default
        folder_id = args.folder_id or os.getenv("OXOS_GOOGLE_DRIVE_FOLDER_ID", "1qk1kb6BDSVkdNvFGCzXTq0q5aL1bTlSR")
        
        # Initialize and configure generator
        generator = GoogleDriveSidebarGenerator()
        
        generator.load_credentials({
            DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: service_account_json,
            DB_CREDENTIALS_PRIMARY_ADMIN_KEY: primary_admin_email,
        })
        
        # Get all files from the folder
        files = generator.get_files_from_folder(folder_id)
        
        # Create the output structure
        output = {
            "files": files
        }
        
        # Write out the files to a JSON file
        with open("sidebar_files.json", "w") as f:
            json.dump(output, f, indent=2)
            
        print(f"Successfully generated sidebar_files.json with {len(files)} top-level items")
        
    except Exception as e:
        print(f"Error running sidebar file generator: {str(e)}")
        raise e

if __name__ == "__main__":
    """
    Run Command: PYTHONPATH=/Users/steven/Desktop/repos/onyx/onyx/backend python3 /Users/steven/Desktop/repos/onyx/onyx/backend/onyx/connectors/oxos_google_drive/sidebar_file_generator.py --folder-id YOUR_FOLDER_ID
    """
    main()
