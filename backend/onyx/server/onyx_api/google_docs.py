import os
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from typing import Any, List, Dict, Optional

from onyx.auth.users import api_key_dep
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.resources import get_google_docs_service, get_drive_service
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.section_extraction import get_document_sections
from onyx.connectors.google_drive.doc_conversion import _download_and_extract_sections_basic
from onyx.db.models import User
from onyx.utils.logger import setup_logger
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.models import TextSection, ImageSection

logger = setup_logger()

router = APIRouter(prefix="/google")

ALLOWED_DOMAINS = ["getvalkai.com", "oxos.com"]


def verify_user_domain(user: User) -> None:
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
async def get_google_doc_content(
    doc_id: str,
    user: User = Depends(api_key_dep),
) -> Dict[str, Any]:
    """
    Retrieve Google Docs content by document ID.
    Limited to users with @getvalkai.com and @oxos.com email domains.
    """
    verify_user_domain(user)
    
    try:
        creds, primary_admin_email = get_google_credentials()
        docs_service = get_google_docs_service(creds, user_email=primary_admin_email)
        drive_service = get_drive_service(creds, user_email=primary_admin_email)
        
        file_info = drive_service.files().get(fileId=doc_id, fields="id,name,mimeType").execute()
        mime_type = file_info.get("mimeType", "")
        
        if mime_type != GDriveMimeType.DOC.value:
            raise HTTPException(
                status_code=400,
                detail=f"The provided ID is not a Google Doc. Found: {mime_type}"
            )
        
        try:
            doc_sections = get_document_sections(docs_service, doc_id)
            
            if not doc_sections:
                file_obj = {
                    "id": doc_id,
                    "name": file_info.get("name", ""),
                    "mimeType": mime_type,
                    "webViewLink": f"https://docs.google.com/document/d/{doc_id}/edit"
                }
                doc_sections = _download_and_extract_sections_basic(file_obj, drive_service, allow_images=True)
            
            if not doc_sections:
                raise HTTPException(
                    status_code=404,
                    detail=f"No content found for document ID: {doc_id}"
                )
            
            return {
                "document_id": doc_id,
                "type": "google_doc",
                "sections": format_for_tiptap(doc_sections)
            }
        except Exception as e:
            logger.error(f"Failed to retrieve Google Doc {doc_id}: {e}")
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to retrieve document: {str(e)}"
            )
    except Exception as e:
        logger.error(f"Failed to retrieve Google Doc {doc_id}: {e}")
        raise HTTPException(
            status_code=400, 
            detail=f"Failed to retrieve document: {str(e)}"
        )


@router.get("/sheets/{sheet_id}")
async def get_google_sheet_content(
    sheet_id: str,
    user: User = Depends(api_key_dep),
) -> Dict[str, Any]:
    """
    Retrieve Google Sheets content by sheet ID.
    Limited to users with @getvalkai.com and @oxos.com email domains.
    """
    verify_user_domain(user)
    
    try:
        creds, primary_admin_email = get_google_credentials()
        drive_service = get_drive_service(creds, user_email=primary_admin_email)
        
        file_info = drive_service.files().get(fileId=sheet_id, fields="id,name,mimeType").execute()
        
        mime_type = file_info.get("mimeType", "")
        if mime_type != GDriveMimeType.SPREADSHEET.value:
            raise HTTPException(
                status_code=400,
                detail=f"The provided ID is not a Google Sheet. Found: {mime_type}"
            )
        
        file_obj = {
            "id": sheet_id,
            "name": file_info.get("name", ""),
            "mimeType": mime_type,
            "webViewLink": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        }
        
        sections = _download_and_extract_sections_basic(file_obj, drive_service, allow_images=False)
        
        if not sections:
            raise HTTPException(
                status_code=404,
                detail=f"No content found for sheet ID: {sheet_id}"
            )
        
        return {
            "document_id": sheet_id,
            "type": "google_sheet",
            "sections": format_for_tiptap(sections)
        }
    except Exception as e:
        logger.error(f"Failed to retrieve Google Sheet {sheet_id}: {e}")
        raise HTTPException(
            status_code=400, 
            detail=f"Failed to retrieve sheet: {str(e)}"
        )
