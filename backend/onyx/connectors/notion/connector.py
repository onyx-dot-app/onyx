"""Notion connector for indexing pages and databases from Notion workspaces.

Uses API version 2025-09-03 which supports multi-source databases.
Database rows (pages in databases) are ingested as full documents with their properties.
Page properties are included in both the document content and metadata fields.

Reference: https://developers.notion.com/docs/working-with-databases
"""

from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

import requests
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.connectors.notion.models import NotionBlock
from onyx.connectors.notion.models import NotionPage
from onyx.connectors.notion.models import NotionSearchResponse
from onyx.connectors.notion.utils import build_page_metadata
from onyx.connectors.notion.utils import extract_page_title
from onyx.connectors.notion.utils import properties_to_str
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NOTION_PAGE_SIZE = 100
_NOTION_CALL_TIMEOUT = 30  # seconds


class NotionConnector(LoadConnector, PollConnector):
    """Notion connector that reads pages and databases from Notion workspaces.

    Supports both search API and recursive traversal modes. When recursive_index_enabled
    is True, traverses pages recursively. Otherwise uses the search API (though it may
    miss some pages).

    Args:
        batch_size: Number of documents to yield per batch
        recursive_index_enabled: Whether to use recursive traversal instead of search API
        root_page_id: Optional root page ID to scope indexing to a specific page tree
    """

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        recursive_index_enabled: bool = not NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP,
        root_page_id: str | None = None,
    ) -> None:
        """Initialize the Notion connector."""
        self.batch_size = batch_size
        self.headers = {
            "Content-Type": "application/json",
            "Notion-Version": "2025-09-03",
        }
        self.indexed_pages: set[str] = set()
        self.root_page_id = root_page_id
        # if enabled, will recursively index child pages as they are found rather
        # relying entirely on the `search` API. We have received reports that the
        # `search` API misses many pages - in those cases, this might need to be
        # turned on. It's not currently known why/when this is required.
        # NOTE: this also removes all benefits polling, since we need to traverse
        # all pages regardless of if they are updated. If the notion workspace is
        # very large, this may not be practical.
        self.recursive_index_enabled = recursive_index_enabled or self.root_page_id

    # ==================== Credentials & Validation ====================

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load Notion integration token."""
        self.headers["Authorization"] = (
            f'Bearer {credentials["notion_integration_token"]}'
        )
        return None

    def validate_connector_settings(self) -> None:
        """Validate connector settings and credentials."""
        if not self.headers.get("Authorization"):
            raise ConnectorMissingCredentialError("Notion credentials not loaded.")

        try:
            if self.root_page_id:
                res = rl_requests.get(
                    f"https://api.notion.com/v1/pages/{self.root_page_id}",
                    headers=self.headers,
                    timeout=_NOTION_CALL_TIMEOUT,
                )
            else:
                # If root_page_id is not set, perform a minimal search
                test_query = {
                    "filter": {"property": "object", "value": "page"},
                    "page_size": 1,
                }
                res = rl_requests.post(
                    "https://api.notion.com/v1/search",
                    headers=self.headers,
                    json=test_query,
                    timeout=_NOTION_CALL_TIMEOUT,
                )
            res.raise_for_status()

        except requests.exceptions.HTTPError as http_err:
            status_code = http_err.response.status_code if http_err.response else None

            if status_code == 401:
                raise CredentialExpiredError(
                    "Notion credential appears to be invalid or expired (HTTP 401)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Your Notion token does not have sufficient permissions (HTTP 403)."
                )
            elif status_code == 404:
                raise ConnectorValidationError(
                    "Notion resource not found or not shared with the integration (HTTP 404)."
                )
            elif status_code == 429:
                raise ConnectorValidationError(
                    "Validation failed due to Notion rate-limits being exceeded (HTTP 429). "
                    "Please try again later."
                )
            else:
                raise UnexpectedValidationError(
                    f"Unexpected Notion HTTP error (status={status_code}): {http_err}"
                ) from http_err

        except Exception as exc:
            raise UnexpectedValidationError(
                f"Unexpected error during Notion settings validation: {exc}"
            ) from exc

    # ==================== Notion API Client Methods ====================

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_page(self, page_id: str) -> NotionPage:
        """Fetch a page by ID, handling both pages and databases."""
        logger.debug(f"Fetching page for ID '{page_id}'")
        page_url = f"https://api.notion.com/v1/pages/{page_id}"
        res = rl_requests.get(
            page_url,
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            logger.warning(
                f"Failed to fetch page, trying database for ID '{page_id}'. Exception: {e}"
            )
            # Try fetching as a database if page fetch fails
            return self._fetch_database_as_page(page_id)
        return NotionPage(**res.json())

    @retry(tries=3, delay=1, backoff=2)
    def _get_database_data_sources(self, database_id: str) -> list[str]:
        """Get data source IDs for a database."""
        logger.debug(f"Discovering data sources for database ID '{database_id}'")
        database_url = f"https://api.notion.com/v1/databases/{database_id}"
        res = rl_requests.get(
            database_url,
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            json_data = res.json()
            code = json_data.get("code")
            if code == "object_not_found" or (
                code == "validation_error"
                and "does not contain any data sources" in json_data.get("message", "")
            ):
                logger.error(
                    f"Unable to access database with ID '{database_id}'. "
                    f"This is likely due to the database not being shared "
                    f"with the Onyx integration. Exact exception:\n{e}"
                )
                return []
            logger.exception(f"Error fetching database data sources - {res.json()}")
            raise e

        data = res.json()
        data_sources = data.get("data_sources", [])
        return [ds["id"] for ds in data_sources if "id" in ds]

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_data_source(self, data_source_id: str) -> dict[str, Any]:
        """Fetch a data source by its ID."""
        logger.debug(f"Fetching data source for ID '{data_source_id}'")
        data_source_url = f"https://api.notion.com/v1/data_sources/{data_source_id}"
        res = rl_requests.get(
            data_source_url,
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        res.raise_for_status()
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_database_as_page(self, database_id: str) -> NotionPage:
        """Fetch a database as a page using its first data source."""
        logger.debug(f"Fetching database for ID '{database_id}' as a page")
        data_source_ids = self._get_database_data_sources(database_id)
        if not data_source_ids:
            raise ValueError(f"Database '{database_id}' has no accessible data sources")

        # Fetch database metadata
        database_url = f"https://api.notion.com/v1/databases/{database_id}"
        db_res = rl_requests.get(
            database_url,
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        db_res.raise_for_status()
        database_data = db_res.json()

        # Extract database name
        database_name = None
        title = database_data.get("title")
        if title and isinstance(title, list) and len(title) > 0:
            database_name = title[0].get("text", {}).get("content")

        # Use first data source for properties
        data_source_data = self._fetch_data_source(data_source_ids[0])

        return NotionPage(
            id=database_id,
            created_time=data_source_data.get("created_time", ""),
            last_edited_time=data_source_data.get("last_edited_time", ""),
            archived=data_source_data.get("in_trash", False),
            properties=data_source_data.get("properties", {}),
            url=f"https://notion.so/{database_id.replace('-', '')}",
            database_name=database_name,
        )

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_data_source_query(
        self, data_source_id: str, cursor: str | None = None
    ) -> dict[str, Any]:
        """Query a data source to get its pages."""
        logger.debug(f"Querying data source for ID '{data_source_id}'")
        query_url = f"https://api.notion.com/v1/data_sources/{data_source_id}/query"
        body = None if not cursor else {"start_cursor": cursor}
        res = rl_requests.post(
            query_url,
            headers=self.headers,
            json=body,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            json_data = res.json()
            code = json_data.get("code")
            if code == "object_not_found":
                logger.error(
                    f"Unable to access data source with ID '{data_source_id}'. "
                    f"This is likely due to the data source not being shared "
                    f"with the Onyx integration. Exact exception:\n{e}"
                )
                return {"results": [], "next_cursor": None}
            logger.exception(f"Error querying data source - {res.json()}")
            raise e
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_database(
        self, database_id: str, cursor: str | None = None
    ) -> dict[str, Any]:
        """Query a database (uses first data source for backward compatibility)."""
        logger.debug(f"Fetching database for ID '{database_id}'")
        data_source_ids = self._get_database_data_sources(database_id)
        if not data_source_ids:
            logger.error(f"Database '{database_id}' has no accessible data sources")
            return {"results": [], "next_cursor": None}

        # Query the first data source (for backward compatibility)
        # TODO: In the future, we may want to query all data sources and merge results
        return self._fetch_data_source_query(data_source_ids[0], cursor)

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_child_blocks(
        self, block_id: str, cursor: str | None = None
    ) -> dict[str, Any] | None:
        """Fetch child blocks of a page."""
        logger.debug(f"Fetching children of block with ID '{block_id}'")
        block_url = f"https://api.notion.com/v1/blocks/{block_id}/children"
        query_params = None if not cursor else {"start_cursor": cursor}
        res = rl_requests.get(
            block_url,
            headers=self.headers,
            params=query_params,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            if res.status_code == 404:
                logger.error(
                    f"Unable to access block with ID '{block_id}'. "
                    f"This is likely due to the block not being shared "
                    f"with the Onyx integration. Exact exception:\n\n{e}"
                )
            else:
                logger.exception(
                    f"Error fetching blocks with status code {res.status_code}: {res.json()}"
                )
            return None
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _search_notion(self, query_dict: dict[str, Any]) -> NotionSearchResponse:
        """Search for pages using the Notion Search API.

        With API version 2025-09-03, search results may include data_source objects
        instead of database objects. We filter these out since we only process pages.
        """
        logger.debug(f"Searching for pages in Notion with query_dict: {query_dict}")
        res = rl_requests.post(
            "https://api.notion.com/v1/search",
            headers=self.headers,
            json=query_dict,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        res.raise_for_status()
        search_response = res.json()

        # Filter out data_source objects - we only process pages
        filtered_results = [
            result
            for result in search_response.get("results", [])
            if result.get("object") == "page"
        ]
        search_response["results"] = filtered_results

        return NotionSearchResponse(**search_response)

    # ==================== Content Processing ====================

    def _read_blocks(self, base_block_id: str) -> tuple[list[NotionBlock], list[str]]:
        """Read all blocks from a page and discover child pages."""
        result_blocks: list[NotionBlock] = []
        child_pages: list[str] = []
        cursor = None

        while True:
            data = self._fetch_child_blocks(base_block_id, cursor)
            if data is None:
                return result_blocks, child_pages

            for result in data["results"]:
                result_block_id = result["id"]
                result_type = result["type"]
                result_obj = result[result_type]

                # Skip unsupported block types
                if result_type in (
                    "ai_block",
                    "unsupported",
                    "external_object_instance_page",
                ):
                    logger.debug(f"Skipping unsupported block type '{result_type}'")
                    continue

                # Extract text content
                cur_result_text_arr = []
                if "rich_text" in result_obj:
                    for rich_text in result_obj["rich_text"]:
                        if "text" in rich_text:
                            cur_result_text_arr.append(rich_text["text"]["content"])

                # Handle nested blocks
                if result["has_children"]:
                    if result_type == "child_page":
                        child_pages.append(result_block_id)
                    else:
                        logger.debug(f"Entering sub-block: {result_block_id}")
                        subblocks, subblock_child_pages = self._read_blocks(
                            result_block_id
                        )
                        result_blocks.extend(subblocks)
                        child_pages.extend(subblock_child_pages)

                # Handle embedded databases
                if result_type == "child_database":
                    inner_blocks, inner_child_pages = self._read_pages_from_database(
                        result_block_id
                    )
                    result_blocks.extend(inner_blocks)
                    if self.recursive_index_enabled:
                        child_pages.extend(inner_child_pages)

                # Add text block
                if cur_result_text_arr:
                    result_blocks.append(
                        NotionBlock(
                            id=result_block_id,
                            text="\n".join(cur_result_text_arr),
                            prefix="\n",
                        )
                    )

            if data["next_cursor"] is None:
                break
            cursor = data["next_cursor"]

        return result_blocks, child_pages

    def _read_pages_from_database(
        self, database_id: str
    ) -> tuple[list[NotionBlock], list[str]]:
        """Read pages from a database and return blocks and page IDs.

        With API version 2025-09-03, reads from all data sources in the database.
        Database rows (pages) are ingested as full documents with their properties.
        """
        result_blocks: list[NotionBlock] = []
        result_pages: list[str] = []

        data_source_ids = self._get_database_data_sources(database_id)
        if not data_source_ids:
            logger.warning(
                f"Database '{database_id}' has no accessible data sources, skipping"
            )
            return result_blocks, result_pages

        # Query all data sources in the database
        for data_source_id in data_source_ids:
            cursor = None
            while True:
                data = self._fetch_data_source_query(data_source_id, cursor)

                for result in data["results"]:
                    obj_id = result["id"]
                    obj_type = result["object"]

                    # Convert properties to text for inline table display
                    text = properties_to_str(result.get("properties", {}))
                    if text:
                        result_blocks.append(
                            NotionBlock(id=obj_id, text=text, prefix="\n")
                        )

                    # Collect page IDs for recursive indexing
                    if self.recursive_index_enabled:
                        if obj_type == "page":
                            logger.debug(
                                f"Found page (database row) with ID '{obj_id}' in database '{database_id}' "
                                f"(data source '{data_source_id}')"
                            )
                            result_pages.append(obj_id)
                        elif obj_type == "database":
                            # Nested database - recurse
                            _, child_pages = self._read_pages_from_database(obj_id)
                            result_pages.extend(child_pages)

                if data["next_cursor"] is None:
                    break
                cursor = data["next_cursor"]

        return result_blocks, result_pages

    def _read_pages(self, pages: list[NotionPage]) -> Generator[Document, None, None]:
        """Read pages and generate Document objects.

        Processes page content, properties, and metadata. Recursively processes
        child pages if recursive_index_enabled is True.
        """
        all_child_page_ids: list[str] = []

        for page in pages:
            if page.id in self.indexed_pages:
                logger.debug(f"Already indexed page with ID '{page.id}'. Skipping.")
                continue

            logger.info(f"Reading page with ID '{page.id}', with url {page.url}")
            page_blocks, child_page_ids = self._read_blocks(page.id)
            all_child_page_ids.extend(child_page_ids)
            self.indexed_pages.add(page.id)

            # Extract title and properties
            page_title = extract_page_title(page.properties, page.database_name) or (
                f"Untitled Page with ID {page.id}"
            )
            properties_text = properties_to_str(page.properties)

            # Build metadata
            page_metadata = build_page_metadata(
                page_id=page.id,
                page_url=page.url,
                created_time=page.created_time,
                last_edited_time=page.last_edited_time,
                archived=page.archived,
                properties=page.properties,
            )

            # Build document sections
            sections = self._build_page_sections(
                page, page_blocks, page_title, properties_text
            )
            if not sections:
                logger.warning(
                    f"No blocks or properties found for page with ID '{page.id}'. Skipping."
                )
                continue

            yield Document(
                id=page.id,
                sections=cast(list[TextSection | ImageSection], sections),
                source=DocumentSource.NOTION,
                semantic_identifier=page_title,
                doc_updated_at=datetime.fromisoformat(page.last_edited_time).astimezone(
                    timezone.utc
                ),
                metadata=page_metadata,
            )
            self.indexed_pages.add(page.id)

        # Recursively process child pages
        if self.recursive_index_enabled and all_child_page_ids:
            for child_page_batch_ids in batch_generator(
                all_child_page_ids, batch_size=INDEX_BATCH_SIZE
            ):
                child_page_batch = [
                    self._fetch_page(page_id)
                    for page_id in child_page_batch_ids
                    if page_id not in self.indexed_pages
                ]
                yield from self._read_pages(child_page_batch)

    def _build_page_sections(
        self,
        page: NotionPage,
        page_blocks: list[NotionBlock],
        page_title: str,
        properties_text: str,
    ) -> list[TextSection | ImageSection]:
        """Build document sections from page content and properties."""
        sections: list[TextSection | ImageSection] = []

        if not page_blocks:
            # Page with no blocks - include title and properties
            text_parts = []
            if page_title:
                text_parts.append(page_title)
            if properties_text:
                text_parts.append(properties_text.strip())

            if text_parts:
                sections.append(
                    TextSection(
                        link=page.url,
                        text="\n\n".join(text_parts),
                    )
                )
        else:
            # Page with blocks - include properties first, then blocks
            if properties_text:
                sections.append(
                    TextSection(
                        link=page.url,
                        text=properties_text.strip(),
                    )
                )

            sections.extend(
                [
                    TextSection(
                        link=f"{page.url}#{block.id.replace('-', '')}",
                        text=block.prefix + block.text,
                    )
                    for block in page_blocks
                ]
            )

        return sections

    # ==================== Search & Filtering ====================

    def _filter_pages_by_time(
        self,
        pages: list[dict[str, Any]],
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        filter_field: str = "last_edited_time",
    ) -> list[NotionPage]:
        """Filter pages by last_edited_time within the specified range."""
        filtered_pages: list[NotionPage] = []
        for page in pages:
            timestamp = page[filter_field].replace(".000Z", "+00:00")
            compare_time = datetime.fromisoformat(timestamp).timestamp()
            if compare_time > start and compare_time <= end:
                filtered_pages.append(NotionPage(**page))
        return filtered_pages

    # ==================== Public Interface ====================

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all pages from a Notion workspace."""
        if self.recursive_index_enabled and self.root_page_id:
            yield from self._recursive_load()
            return

        query_dict = {
            "filter": {"property": "object", "value": "page"},
            "page_size": _NOTION_PAGE_SIZE,
        }
        while True:
            db_res = self._search_notion(query_dict)
            pages = [NotionPage(**page) for page in db_res.results]
            yield from batch_generator(self._read_pages(pages), self.batch_size)
            if db_res.has_more:
                query_dict["start_cursor"] = db_res.next_cursor
            else:
                break

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Poll for pages updated within the time range."""
        if self.recursive_index_enabled and self.root_page_id:
            yield from self._recursive_load()
            return

        query_dict = {
            "page_size": _NOTION_PAGE_SIZE,
            "sort": {"timestamp": "last_edited_time", "direction": "descending"},
            "filter": {"property": "object", "value": "page"},
        }
        while True:
            db_res = self._search_notion(query_dict)
            pages = self._filter_pages_by_time(
                db_res.results, start, end, filter_field="last_edited_time"
            )
            if len(pages) > 0:
                yield from batch_generator(self._read_pages(pages), self.batch_size)
                if db_res.has_more:
                    query_dict["start_cursor"] = db_res.next_cursor
                else:
                    break
            else:
                break

    def _recursive_load(self) -> Generator[list[Document], None, None]:
        """Load pages recursively starting from root_page_id."""
        if self.root_page_id is None or not self.recursive_index_enabled:
            raise RuntimeError(
                "Recursive page lookup is not enabled, but we are trying to "
                "recursively load pages. This should never happen."
            )

        logger.info(
            "Recursively loading pages from Notion based on root page with "
            f"ID: {self.root_page_id}"
        )
        pages = [self._fetch_page(page_id=self.root_page_id)]
        yield from batch_generator(self._read_pages(pages), self.batch_size)


if __name__ == "__main__":
    import os

    root_page_id = os.environ.get("NOTION_ROOT_PAGE_ID")
    connector = NotionConnector(root_page_id=root_page_id)
    connector.load_credentials(
        {"notion_integration_token": os.environ.get("NOTION_INTEGRATION_TOKEN")}
    )
    document_batches = connector.load_from_state()
    for doc_batch in document_batches:
        for doc in doc_batch:
            print(doc)
