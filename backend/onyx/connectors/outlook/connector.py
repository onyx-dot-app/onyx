import os
from datetime import datetime
from datetime import timezone
from typing import Any, Optional

import msal  # type: ignore
import requests
from requests.exceptions import RequestException

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OutlookConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        indexing_scope: str = "everything",
        folders: list[str] = [],
        email_addresses: list[str] = [],
        include_attachments: bool = True,
        start_date: str | None = None,
        include_metadata: bool = False,
        max_emails: int | None = None,
    ) -> None:
        self.batch_size = batch_size
        self.access_token: Optional[str] = None
        self.indexing_scope = indexing_scope
        self.folders = folders
        self.email_addresses = email_addresses
        self.include_attachments = include_attachments
        self.start_date = start_date
        self.include_metadata = include_metadata
        self.max_emails = max_emails
        self.msal_app: Optional[msal.ConfidentialClientApplication] = None
        self.base_url = "https://graph.microsoft.com/v1.0"

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        outlook_client_id = credentials["outlook_client_id"]
        outlook_client_secret = credentials["outlook_client_secret"]
        outlook_directory_id = credentials["outlook_directory_id"]

        authority_url = f"https://login.microsoftonline.com/{outlook_directory_id}"
        self.msal_app = msal.ConfidentialClientApplication(
            authority=authority_url,
            client_id=outlook_client_id,
            client_credential=outlook_client_secret,
        )
        return None

    def _get_access_token(self) -> str:
        if self.msal_app is None:
            raise ConnectorMissingCredentialError("Outlook credentials not loaded.")

        token = self.msal_app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in token:
            raise CredentialExpiredError("Failed to acquire access token")
        return token["access_token"]

    def _make_request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        if not self.access_token:
            self.access_token = self._get_access_token()

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.get(
                f"{self.base_url}/{endpoint}",
                headers=headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            if e.response is not None:
                status_code = e.response.status_code
                if status_code == 401:
                    # Token might be expired, try to get a new one
                    self.access_token = None
                    return self._make_request(endpoint, params)
                elif status_code == 403:
                    raise InsufficientPermissionsError(
                        "Your app lacks sufficient permissions to read Outlook (403 Forbidden)."
                    )
            raise UnexpectedValidationError(f"Error making request to Graph API: {e}")

    def _get_messages(
        self,
        folder_id: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[dict]:
        endpoint = "me/messages" if not folder_id else f"me/mailFolders/{folder_id}/messages"
        
        params = {}
        if start:
            params["$filter"] = f"receivedDateTime ge {start.isoformat()}"
        if end:
            if "$filter" in params:
                params["$filter"] += f" and receivedDateTime le {end.isoformat()}"
            else:
                params["$filter"] = f"receivedDateTime le {end.isoformat()}"
        
        params["$select"] = "id,subject,body,receivedDateTime,from,toRecipients,hasAttachments,importance,categories,isRead,isDraft,webLink,conversationId"
        
        response = self._make_request(endpoint, params)
        return response.get("value", [])

    def _get_folders(self) -> list[dict]:
        response = self._make_request("me/mailFolders")
        return response.get("value", [])

    def _get_attachment(self, message_id: str, attachment_id: str) -> Optional[str]:
        try:
            response = self._make_request(f"me/messages/{message_id}/attachments/{attachment_id}")
            if response.get("contentType", "").startswith("text/"):
                return response.get("contentBytes")
            return None
        except Exception as e:
            logger.error(f"Error fetching attachment: {e}")
            return None

    def _fetch_from_outlook(
        self, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> GenerateDocumentsOutput:
        if not self.msal_app:
            raise ConnectorMissingCredentialError("Outlook")

        # Get folders based on indexing scope
        folders_to_index = []
        if self.indexing_scope == "folders":
            # Get specific folders
            all_folders = self._get_folders()
            folders_to_index = [
                folder["id"] for folder in all_folders 
                if folder["displayName"] in self.folders
            ]
        elif self.indexing_scope == "emails":
            # Get specific email addresses
            for email in self.email_addresses:
                messages = self._get_messages(start=start, end=end)
                doc_batch: list[Document] = []
                
                for message in messages:
                    if self.max_emails and len(doc_batch) >= self.max_emails:
                        yield doc_batch
                        doc_batch = []
                    
                    doc = self._convert_message_to_document(message)
                    if doc:
                        doc_batch.append(doc)
                    
                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch = []
                
                if doc_batch:
                    yield doc_batch
        else:
            # Index everything
            folders_to_index = [None]  # None means root folder

        # Process messages from each folder
        for folder_id in folders_to_index:
            messages = self._get_messages(folder_id, start, end)
            doc_batch: list[Document] = []
            
            for message in messages:
                if self.max_emails and len(doc_batch) >= self.max_emails:
                    yield doc_batch
                    doc_batch = []
                
                doc = self._convert_message_to_document(message)
                if doc:
                    doc_batch.append(doc)
                
                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []
            
            if doc_batch:
                yield doc_batch

    def _convert_message_to_document(self, message: dict) -> Optional[Document]:
        try:
            # Get message content
            content = message.get("body", {}).get("content")
            if not content:
                return None

            # Get attachments if enabled
            attachments = []
            if self.include_attachments and message.get("hasAttachments"):
                attachments_response = self._make_request(f"me/messages/{message['id']}/attachments")
                for attachment in attachments_response.get("value", []):
                    attachment_content = self._get_attachment(message["id"], attachment["id"])
                    if attachment_content:
                        attachments.append(attachment_content)

            # Create document
            doc = Document(
                id=str(message["id"]),
                title=message.get("subject", "No Subject"),
                content=content,
                source_type=DocumentSource.OUTLOOK,
                semantic_identifier=message.get("subject", "No Subject"),
                doc_updated_at=time_str_to_utc(message["receivedDateTime"]),
                primary_owners=[
                    BasicExpertInfo(
                        email=message["from"]["emailAddress"]["address"],
                        full_name=message["from"]["emailAddress"].get("name", ""),
                    )
                ],
                secondary_owners=[
                    BasicExpertInfo(
                        email=recipient["emailAddress"]["address"],
                        full_name=recipient["emailAddress"].get("name", ""),
                    )
                    for recipient in message.get("toRecipients", [])
                ],
                sections=[
                    TextSection(
                        text=content,
                        semantic_identifier=message.get("subject", "No Subject"),
                    )
                ],
            )

            # Add metadata if enabled
            if self.include_metadata:
                doc.metadata = {
                    "message_id": message["id"],
                    "conversation_id": message.get("conversationId"),
                    "importance": message.get("importance"),
                    "categories": message.get("categories", []),
                    "has_attachments": message.get("hasAttachments", False),
                    "is_read": message.get("isRead", False),
                    "is_draft": message.get("isDraft", False),
                    "web_link": message.get("webLink"),
                }

            return doc

        except Exception as e:
            logger.error(f"Error converting message to document: {e}")
            return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_from_outlook()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, timezone.utc)
        end_datetime = datetime.fromtimestamp(end, timezone.utc)
        return self._fetch_from_outlook(start=start_datetime, end=end_datetime)

    def validate_connector_settings(self) -> None:
        if not self.msal_app:
            raise ConnectorMissingCredentialError("Outlook credentials not loaded.")

        try:
            # Minimal call to confirm we can retrieve messages
            self._get_messages()

        except Exception as e:
            if "401" in str(e):
                raise CredentialExpiredError(
                    "Invalid or expired Outlook credentials (401 Unauthorized)."
                )
            elif "403" in str(e):
                raise InsufficientPermissionsError(
                    "Your app lacks sufficient permissions to read Outlook (403 Forbidden)."
                )
            raise ConnectorValidationError(f"Unexpected error during Outlook validation: {e}") 