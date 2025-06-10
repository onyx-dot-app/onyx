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
from onyx.connectors.models import TextSection
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
    """Extract text content from GitBook document structure by parsing the document nodes
    into markdown format."""

    def parse_leaf(leaf: dict[str, Any]) -> str:
        text = leaf.get("text", "")
        leaf.get("marks", [])
        return text

    def parse_text_node(node: dict[str, Any]) -> str:
        text = ""
        for leaf in node.get("leaves", []):
            text += parse_leaf(leaf)
        return text

    def parse_block_node(node: dict[str, Any]) -> str:
        block_type = node.get("type", "")
        result = ""

        if block_type == "heading-1":
            text = "".join(parse_text_node(n) for n in node.get("nodes", []))
            result = f"# {text}\n\n"

        elif block_type == "heading-2":
            text = "".join(parse_text_node(n) for n in node.get("nodes", []))
            result = f"## {text}\n\n"

        elif block_type == "heading-3":
            text = "".join(parse_text_node(n) for n in node.get("nodes", []))
            result = f"### {text}\n\n"

        elif block_type == "heading-4":
            text = "".join(parse_text_node(n) for n in node.get("nodes", []))
            result = f"#### {text}\n\n"

        elif block_type == "heading-5":
            text = "".join(parse_text_node(n) for n in node.get("nodes", []))
            result = f"##### {text}\n\n"

        elif block_type == "heading-6":
            text = "".join(parse_text_node(n) for n in node.get("nodes", []))
            result = f"###### {text}\n\n"

        elif block_type == "list-unordered":
            for list_item in node.get("nodes", []):
                paragraph = list_item.get("nodes", [])[0]
                text = "".join(parse_text_node(n) for n in paragraph.get("nodes", []))
                result += f"* {text}\n"
            result += "\n"

        elif block_type == "paragraph":
            text = "".join(parse_text_node(n) for n in node.get("nodes", []))
            result = f"{text}\n\n"

        elif block_type == "list-tasks":
            for task_item in node.get("nodes", []):
                checked = task_item.get("data", {}).get("checked", False)
                paragraph = task_item.get("nodes", [])[0]
                text = "".join(parse_text_node(n) for n in paragraph.get("nodes", []))
                checkbox = "[x]" if checked else "[ ]"
                result += f"- {checkbox} {text}\n"
            result += "\n"

        elif block_type == "code":
            for code_line in node.get("nodes", []):
                if code_line.get("type") == "code-line":
                    text = "".join(
                        parse_text_node(n) for n in code_line.get("nodes", [])
                    )
                    result += f"{text}\n"
            result += "\n"

        elif block_type == "blockquote":
            for quote_node in node.get("nodes", []):
                if quote_node.get("type") == "paragraph":
                    text = "".join(
                        parse_text_node(n) for n in quote_node.get("nodes", [])
                    )
                    result += f"> {text}\n"
            result += "\n"

        elif block_type == "table":
            records = node.get("data", {}).get("records", {})
            definition = node.get("data", {}).get("definition", {})
            view = node.get("data", {}).get("view", {})

            columns = view.get("columns", [])

            header_cells = []
            for col_id in columns:
                col_def = definition.get(col_id, {})
                header_cells.append(col_def.get("title", ""))

            result = "| " + " | ".join(header_cells) + " |\n"
            result += "|" + "---|" * len(header_cells) + "\n"

            sorted_records = sorted(
                records.items(), key=lambda x: x[1].get("orderIndex", "")
            )

            for record_id, record_data in sorted_records:
                values = record_data.get("values", {})
                row_cells = []
                for col_id in columns:
                    fragment_id = values.get(col_id, "")
                    fragment_text = ""
                    for fragment in node.get("fragments", []):
                        if fragment.get("fragment") == fragment_id:
                            for frag_node in fragment.get("nodes", []):
                                if frag_node.get("type") == "paragraph":
                                    fragment_text = "".join(
                                        parse_text_node(n)
                                        for n in frag_node.get("nodes", [])
                                    )
                                    break
                    row_cells.append(fragment_text)
                result += "| " + " | ".join(row_cells) + " |\n"

            result += "\n"
        return result

    if not document or "document" not in document:
        return ""

    markdown = ""
    nodes = document["document"].get("nodes", [])

    for node in nodes:
        markdown += parse_block_node(node)

    return markdown


def _convert_page_to_document(
    client: GitbookApiClient, space_id: str, page: dict[str, Any]
) -> Document:
    page_id = page["id"]
    page_content = client.get_page_content(space_id, page_id)

    return Document(
        id=f"gitbook-{space_id}-{page_id}",
        sections=[
            TextSection(
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
            content = self.client.get(f"/spaces/{self.space_id}/content/pages")
            pages: list[dict[str, Any]] = content.get("pages", [])
            current_batch: list[Document] = []

            logger.info(f"Found {len(pages)} root pages.")
            logger.info(
                f"First 20 Page Ids: {[page.get('id', 'Unknown') for page in pages[:20]]}"
            )

            while pages:
                page = pages.pop(0)

                updated_at_raw = page.get("updatedAt")
                if updated_at_raw is None:
                    # if updatedAt is not present, that means the page has never been edited
                    continue

                updated_at = datetime.fromisoformat(updated_at_raw)
                if start and updated_at < start:
                    continue
                if end and updated_at > end:
                    continue

                current_batch.append(
                    _convert_page_to_document(self.client, self.space_id, page)
                )

                if len(current_batch) >= self.batch_size:
                    yield current_batch
                    current_batch = []

                pages.extend(page.get("pages", []))

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
