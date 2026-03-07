import datetime
from collections.abc import Generator
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorMissingCredentialError
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.resources import get_google_chat_service
from onyx.connectors.google_utils.resources import GoogleChatService
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

class GoogleChatConfig(BaseModel):
    # Depending on requirements, we might want to filter by space names
    # For now, we will fetch all spaces
    pass

class GoogleChatConnector(SlimConnectorWithPermSync):
    def __init__(self, **kwargs: Any) -> None:
        self.config = GoogleChatConfig(**kwargs)
        self.creds = None
        self._chat_service: GoogleChatService | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        self.creds = get_google_creds(credentials)
        if not self.creds:
            raise ConnectorMissingCredentialError("Google Chat")
        self._chat_service = get_google_chat_service(self.creds)

    @property
    def chat_service(self) -> GoogleChatService:
        if self._chat_service is None:
            raise ConnectorMissingCredentialError("Google Chat")
        return self._chat_service

    def retrieve_all_slim_documents(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> Generator[GenerateSlimDocumentOutput, None, None]:
        # Step 1: List all spaces
        request = self.chat_service.spaces().list()
        
        while request is not None:
            response = request.execute()
            spaces = response.get('spaces', [])
            
            for space in spaces:
                space_name = space.get('name') # format: spaces/SPACE_ID
                if not space_name:
                    continue
                
                # Step 2: List messages in the space
                msg_request = self.chat_service.spaces().messages().list(parent=space_name)
                while msg_request is not None:
                    msg_response = msg_request.execute()
                    messages = msg_response.get('messages', [])
                    
                    for msg in messages:
                        yield SlimDocument(id=msg['name'], perm_sync_data=None)
                    
                    msg_request = self.chat_service.spaces().messages().list_next(msg_request, msg_response)
            
            request = self.chat_service.spaces().list_next(request, response)

    def retrieve_full_documents(
        self, slim_documents: list[SlimDocument]
    ) -> Generator[list[Document], None, None]:
        for slim_doc in slim_documents:
            try:
                msg = self.chat_service.spaces().messages().get(name=slim_doc.id).execute()
                
                text_content = msg.get('text', '')
                if not text_content:
                    continue
                    
                sender = msg.get('sender', {}).get('displayName', 'Unknown Sender')
                space_name = msg.get('space', {}).get('name', 'Unknown Space')
                
                create_time_str = msg.get('createTime', '').replace('Z', '+00:00')
                try:
                    create_time = datetime.datetime.fromisoformat(create_time_str)
                except ValueError:
                    create_time = datetime.datetime.now(datetime.timezone.utc)

                yield [
                    Document(
                        id=msg['name'],
                        sections=[TextSection(text=f"{sender}: {text_content}", link=msg.get('thread', {}).get('name', ''))],
                        source=DocumentSource.GOOGLE_CHAT,
                        semantic_identifier=f"Message in {space_name}",
                        title=f"Google Chat Message from {sender}",
                        doc_updated_at=create_time,
                        metadata={
                            "sender": sender,
                            "space": space_name,
                        },
                    )
                ]
            except Exception as e:
                logger.error(f"Failed to fetch message {slim_doc.id}: {e}")
                continue

    def stop_sync(self) -> None:
        pass
