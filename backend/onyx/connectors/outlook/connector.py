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

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

class OutlookConnector(SlimConnectorWithPermSync):
    def __init__(self) -> None:
        self._access_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        self._access_token = credentials.get("access_token")

    @property
    def access_token(self) -> str:
        if self._access_token is None:
            raise ConnectorMissingCredentialError("Outlook")
        return self._access_token

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def retrieve_all_slim_documents(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> Generator[GenerateSlimDocumentOutput, None, None]:
        url = f"{GRAPH_API_BASE}/me/messages"
        params = {
            "$select": "id,subject,receivedDateTime,lastModifiedDateTime",
            "$top": 100,
        }
        while url:
            response = requests.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            data = response.json()
            for message in data.get("value", []):
                yield SlimDocument(id=message["id"], perm_sync_data=None)
            url = data.get("@odata.nextLink")
            params = {}

    def retrieve_full_documents(
        self, slim_documents: list[SlimDocument]
    ) -> Generator[list[Document], None, None]:
        for slim_doc in slim_documents:
            url = f"{GRAPH_API_BASE}/me/messages/{slim_doc.id}"
            response = requests.get(url, headers=self._get_headers())
            if response.status_code == 404: continue
            response.raise_for_status()
            message = response.json()
            yield [
                Document(
                    id=message["id"],
                    sections=[TextSection(text=message.get("body", {}).get("content", ""), link=message.get("webLink"))],
                    source=DocumentSource.OUTLOOK,
                    semantic_identifier=message.get("subject", "No Subject"),
                    title=message.get("subject", "No Subject"),
                    doc_updated_at=datetime.datetime.fromisoformat(message["lastModifiedDateTime"].replace("Z", "+00:00")),
                    metadata={"from": message.get("from", {}).get("emailAddress", {}).get("address"), "subject": message.get("subject")},
                )
            ]

    def stop_sync(self) -> None:
        pass
