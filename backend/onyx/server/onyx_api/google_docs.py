import os
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from typing import Any, List, Dict, Optional

from onyx.auth.users import current_user
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.resources import get_google_docs_service, get_drive_service
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.section_extraction import get_document_sections
from onyx.connectors.google_drive.doc_conversion import _download_and_extract_sections_basic
from onyx.connectors.google_utils.resources import get_sheets_service
from onyx.connectors.google_drive.google_sheets import get_sheet_metadata
from onyx.connectors.google_drive.google_sheets import read_spreadsheet
from onyx.connectors.google_drive.doc_conversion import convert_drive_item_to_document
from onyx.db.models import User
from onyx.utils.logger import setup_logger
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.models import TextSection, ImageSection
from onyx.connectors.google_utils.google_utils import (
    _execute_single_retrieval,
)
from onyx.configs.app_configs import GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document


logger = setup_logger()

router = APIRouter(prefix="/google")

ALLOWED_DOMAINS = ["getvalkai.com", "oxos.com", "test.com"]


def verify_user_domain(user: User | None) -> None:
    """
    Verify that the user's email domain is in the allowed list.
    Raises HTTPException if the user's domain is not allowed.
    """
    if not user or not user.email:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    user_domain = user.email.split("@")[-1] if "@" in user.email else ""
    
    if user_domain not in ALLOWED_DOMAINS:
        raise HTTPException(
            status_code=403, 
            detail=f"Access restricted to {', '.join(ALLOWED_DOMAINS)} domains"
        )


def get_google_credentials():
    """
    Get Google credentials from hardcoded environment variables.
    Returns the credentials needed to access Google Docs/Sheets.
    """
    primary_admin_email = os.getenv("OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL")
    if not primary_admin_email:
        raise HTTPException(
            status_code=500, 
            detail="OXOS_GOOGLE_PRIMARY_ADMIN_EMAIL environment variable not set"
        )

    service_account_json = os.getenv("OXOS_GOOGLE_SERVICE_ACCOUNT_JSON")
    if not service_account_json:
        raise HTTPException(
            status_code=500, 
            detail="OXOS_GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set"
        )

    credentials = {
        DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: service_account_json,
        DB_CREDENTIALS_PRIMARY_ADMIN_KEY: primary_admin_email,
    }

    try:
        creds, _ = get_google_creds(credentials, DocumentSource.GOOGLE_DRIVE)
        return creds, primary_admin_email
    except Exception as e:
        logger.error(f"Failed to load Google credentials: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to load Google credentials: {str(e)}"
        )


def format_for_tiptap(sections: List[TextSection | ImageSection]) -> List[Dict[str, Any]]:
    """
    Format the sections for TipTap compatibility.
    Returns a list of formatted sections.
    """
    formatted_sections = []
    
    for section in sections:
        if isinstance(section, TextSection):
            formatted_section = {
                "type": "text",
                "content": section.text,
                "link": section.link
            }
            formatted_sections.append(formatted_section)
        elif isinstance(section, ImageSection):
            formatted_section = {
                "type": "image",
                "src": section.image_url,
                "alt": section.alt_text or "",
                "link": section.link
            }
            formatted_sections.append(formatted_section)
    
    return formatted_sections


@router.get("/docs/{doc_id}")
def get_google_doc_content(
    doc_id: str,
    user: User | None = Depends(current_user),
) -> Document | ConnectorFailure | None:
    """
    Retrieve Google Docs content by document ID.
    Limited to users with @getvalkai.com and @oxos.com email domains.
    """
    verify_user_domain(user)
    
    try:
        creds, primary_admin_email = get_google_credentials()
        drive_service = get_drive_service(creds, user_email=primary_admin_email)
        
        # Use execute_single_retrieval for better error handling
        file = _execute_single_retrieval(
            retrieval_function=drive_service.files().get,
            fileId=doc_id,
            fields="id,name,mimeType,owners,modifiedTime,createdTime,webViewLink,size",
            supportsAllDrives=True
        )

        # Convert to document
        doc = convert_drive_item_to_document(creds, allow_images=False, size_threshold=GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD, retriever_emails=[primary_admin_email], file=file)

        return doc

    except Exception as e:
        logger.error(f"Failed to retrieve Google Doc {doc_id}: {e}")
        raise HTTPException(
            status_code=400, 
            detail=f"Failed to retrieve document: {str(e)}"
        )


@router.get("/sheets/{spreadsheet_id}")
def get_raw_spreadsheet(
    spreadsheet_id: str,
    user: User | None = Depends(current_user),
) -> dict[str, list]:
    # Authorization check for OxosGoogleDriveConnector usage
    verify_user_domain(user)

    try:
        # Get the sheets service
        creds, primary_admin_email = get_google_credentials()
        sheets_service = get_sheets_service(creds, primary_admin_email)

        # Get metadata about all sheets in the spreadsheet
        metadata = get_sheet_metadata(sheets_service, spreadsheet_id)

        if not metadata.get("sheets"):
            raise ValueError("No sheets found in spreadsheet")

        # Create a dictionary to store all sheet data
        all_sheets_data = {}

        # Iterate through each sheet and get its data
        for sheet in metadata["sheets"]:
            sheet_name = sheet["properties"]["title"]

            # if it's hidden, skip it
            if sheet["properties"].get("hidden", False):
                continue

            # Read the spreadsheet data for this sheet
            sheet_data = read_spreadsheet(
                creds,
                primary_admin_email,
                spreadsheet_id,
                sheet_name=sheet_name
            )

            # Add the sheet data to our result dictionary
            all_sheets_data[sheet_name] = sheet_data.get("values", [])

        return all_sheets_data

    except Exception as e:
        logger.error(f"Error retrieving spreadsheet data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve spreadsheet data: {str(e)}")

