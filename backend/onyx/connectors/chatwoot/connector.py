import datetime
from collections.abc import Generator
from typing import Any

import requests
from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

class ChatwootConfig(BaseModel):
    base_url: str
    account_id: int
    inbox_id: int | None = None

class ChatwootConnector(SlimConnectorWithPermSync):
    def __init__(self, **kwargs: Any) -> None:
        self.config = ChatwootConfig(**kwargs)
        self._api_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        self._api_token = credentials.get("chatwoot_api_token")

    @property
    def api_token(self) -> str:
        if self._api_token is None:
            raise ConnectorMissingCredentialError("Chatwoot")
        return self._api_token

    def _get_headers(self) -> dict[str, str]:
        return {
            "api_access_token": self.api_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def retrieve_all_slim_documents(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> Generator[GenerateSlimDocumentOutput, None, None]:
        url = f"{self.config.base_url.rstrip('/')}/api/v1/accounts/{self.config.account_id}/conversations"
        
        page = 1
        while True:
            params = {"page": page}
            if self.config.inbox_id:
                params["inbox_id"] = self.config.inbox_id
                
            response = requests.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            data = response.json()
            
            conversations = data.get("payload", [])
            if not conversations:
                break
                
            for conv in conversations:
                yield SlimDocument(id=str(conv["id"]), perm_sync_data=None)
                
            page += 1

    def retrieve_full_documents(
        self, slim_documents: list[SlimDocument]
    ) -> Generator[list[Document], None, None]:
        for slim_doc in slim_documents:
            url = f"{self.config.base_url.rstrip('/')}/api/v1/accounts/{self.config.account_id}/conversations/{slim_doc.id}/messages"
            
            response = requests.get(url, headers=self._get_headers())
            if response.status_code == 404:
                continue
            response.raise_for_status()
            messages_data = response.json()
            
            messages = messages_data.get("payload", [])
            if not messages:
                continue
                
            full_text = []
            latest_update = datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc)
            
            for msg in messages:
                sender = msg.get("sender", {}).get("name", "System")
                content = msg.get("content", "")
                if content:
                    full_text.append(f"{sender}: {content}")
                
                created_at = msg.get("created_at")
                if created_at:
                    msg_time = datetime.datetime.fromtimestamp(created_at, tz=datetime.timezone.utc)
                    if msg_time > latest_update:
                        latest_update = msg_time

            conversation_url = f"{self.config.base_url.rstrip('/')}/app/accounts/{self.config.account_id}/conversations/{slim_doc.id}"

            yield [
                Document(
                    id=slim_doc.id,
                    sections=[TextSection(text="\n".join(full_text), link=conversation_url)],
                    source=DocumentSource.CHATWOOT,
                    semantic_identifier=f"Conversation #{slim_doc.id}",
                    title=f"Chatwoot Conversation #{slim_doc.id}",
                    doc_updated_at=latest_update,
                    metadata={
                        "account_id": str(self.config.account_id),
                        "conversation_id": slim_doc.id,
                    },
                )
            ]

    def stop_sync(self) -> None:
        pass
