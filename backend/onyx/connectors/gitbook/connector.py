import time
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urljoin

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.utils.logger import setup_logger


logger = setup_logger()

GITBOOK_API_BASE = "https://api.gitbook.com/v1/"


class GitbookApiClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        url = urljoin(GITBOOK_API_BASE, endpoint.lstrip("/"))
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_page_content(self, space_id: str, page_id: str) -> dict[str, Any]:
        return self.get(f"/spaces/{space_id}/content/page/{page_id}")


def _extract_text_from_document(document: dict[str, Any]) -> str:
    """Extract text content from GitBook document structure"""
    # This is a placeholder - we'll need to implement proper parsing
    # of the document nodes structure later
    return document.get("title", "") + "\n" + str(document.get("document", ""))


def _convert_page_to_document(
    client: GitbookApiClient, space_id: str, page: dict[str, Any]
) -> Document:
    page_id = page["id"]
    page_content = client.get_page_content(space_id, page_id)

    return Document(
        id=f"gitbook-{space_id}-{page_id}",
        sections=[
            Section(
                link=page.get("urls", {}).get("app", ""),
                text=_extract_text_from_document(page_content),
            )
        ],
        source=DocumentSource.GITBOOK,
        semantic_identifier=page.get("title", ""),
        doc_updated_at=datetime.fromisoformat(page["updatedAt"]).replace(
            tzinfo=timezone.utc
        ),
        metadata={
            "path": page.get("path", ""),
            "type": page.get("type", ""),
            "kind": page.get("kind", ""),
        },
    )


class GitbookConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        space_id: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.space_id = space_id
        self.batch_size = batch_size
        self.access_token: str | None = None
        self.client: GitbookApiClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        access_token = credentials.get("gitbook_api_key")
        if not access_token:
            raise ConnectorMissingCredentialError("GitBook access token")
        self.access_token = access_token
        self.client = GitbookApiClient(access_token)

    def _fetch_all_pages(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> GenerateDocumentsOutput:
        if not self.client:
            raise ConnectorMissingCredentialError("GitBook")

        try:
            content = self.client.get(f"/spaces/{self.space_id}/content")
            pages = content.get("pages", [])

            current_batch = []
            for page in pages:
                updated_at = datetime.fromisoformat(page["updatedAt"])

                if start and updated_at < start:
                    if current_batch:
                        yield current_batch
                    return
                if end and updated_at > end:
                    continue

                current_batch.append(
                    _convert_page_to_document(self.client, self.space_id, page)
                )

                if len(current_batch) >= self.batch_size:
                    yield current_batch
                    current_batch = []
                    time.sleep(0.1)  # Rate limiting

            if current_batch:
                yield current_batch

        except requests.RequestException as e:
            logger.error(f"Error fetching GitBook content: {str(e)}")
            raise

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_all_pages()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        return self._fetch_all_pages(start_datetime, end_datetime)


if __name__ == "__main__":
    import os

    connector = GitbookConnector(
        space_id=os.environ["GITBOOK_SPACE_ID"],
    )
    connector.load_credentials({"gitbook_api_key": os.environ["GITBOOK_API_KEY"]})
    document_batches = connector.load_from_state()
    print(next(document_batches))
