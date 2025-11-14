"""Notion connector using API version 2025-09-03.

This connector uses recursive traversal to index all accessible pages and databases.
It supports multi-source databases introduced in API version 2025-09-03.

Reference: https://developers.notion.com/docs/upgrade-guide-2025-09-03
"""

from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

import requests
from retry import retry

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.connectors.notion.models import NotionBlock
from onyx.connectors.notion.models import NotionConnectorCheckpoint
from onyx.connectors.notion.models import NotionPage
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NOTION_CALL_TIMEOUT = 30  # 30 seconds


class NotionConnector(CheckpointedConnector[NotionConnectorCheckpoint]):
    """Notion connector that recursively traverses and indexes all accessible pages.

    Uses API version 2025-09-03 which supports multi-source databases.
    Always uses recursive traversal (no search API) to ensure complete indexing.

    We do not use the search API becase:
    1) it does not always return all pages (no explanation provided)
    2) we cannot filter search by timestamp, which is the primary benefit of using a search API

    Args:
        root_page_id: Optional root page ID to scope indexing to a specific page tree.
            If None, indexes all accessible pages in the workspace.
    """

    def __init__(self, root_page_id: str | None = None) -> None:
        """Initialize the Notion connector."""
        self.headers = {
            "Content-Type": "application/json",
            "Notion-Version": "2025-09-03",
        }
        self.root_page_id = root_page_id

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load Notion integration token."""
        self.headers["Authorization"] = (
            f'Bearer {credentials["notion_integration_token"]}'
        )
        return None

    # ==================== CheckpointedConnector Interface ====================

    def build_dummy_checkpoint(self) -> NotionConnectorCheckpoint:
        """Build an initial checkpoint for a new indexing run."""
        return NotionConnectorCheckpoint(
            has_more=True,
            processed_page_ids=[],
            page_queue=[self.root_page_id] if self.root_page_id else [],
            root_page_id=self.root_page_id,
        )

    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> NotionConnectorCheckpoint:
        """Validate and deserialize checkpoint JSON."""
        return NotionConnectorCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: NotionConnectorCheckpoint,
    ) -> CheckpointOutput[NotionConnectorCheckpoint]:
        """Load documents from Notion using checkpoint-based traversal.

        Traverses pages recursively, yielding documents and tracking progress
        in the checkpoint. Filters pages by last_edited_time within the time range.
        """
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)

        # Initialize queue if empty (first run)
        if not checkpoint.page_queue and checkpoint.has_more:
            if self.root_page_id:
                checkpoint.page_queue = [self.root_page_id]
            else:
                # Need to discover root pages - for now, we require root_page_id
                # In the future, we could use search API to find root pages
                logger.warning(
                    "No root_page_id specified and queue is empty. "
                    "Cannot discover pages without a starting point."
                )
                checkpoint.has_more = False
                return checkpoint

        # Process pages from queue
        while checkpoint.page_queue:
            page_id = checkpoint.page_queue.pop(0)
            processed_set = checkpoint.get_processed_set()

            # Skip if already processed
            if page_id in processed_set:
                continue

            try:
                page = self._fetch_page(page_id)

                # Check if page was edited within time range
                page_edited_time = datetime.fromisoformat(
                    page.last_edited_time.replace("Z", "+00:00")
                ).astimezone(timezone.utc)

                if page_edited_time < start_datetime or page_edited_time > end_datetime:
                    # Page not in time range, but we still need to traverse its children
                    checkpoint.add_processed(page_id)
                    child_page_ids = self._discover_child_pages(page_id)
                    processed_set = checkpoint.get_processed_set()  # Refresh set
                    checkpoint.page_queue.extend(
                        pid for pid in child_page_ids if pid not in processed_set
                    )
                    continue

                # Process page and its children
                document = self._page_to_document(page)
                if document:
                    yield document

                checkpoint.add_processed(page_id)

                # Discover and queue child pages
                child_page_ids = self._discover_child_pages(page_id)
                processed_set = checkpoint.get_processed_set()  # Refresh set
                checkpoint.page_queue.extend(
                    pid for pid in child_page_ids if pid not in processed_set
                )

            except Exception as e:
                logger.exception(f"Error processing page {page_id}: {e}")
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=page_id,
                        document_link=f"https://notion.so/{page_id.replace('-', '')}",
                    ),
                    failure_message=f"Failed to process page {page_id}: {str(e)}",
                )
                checkpoint.add_processed(
                    page_id
                )  # Mark as processed to avoid retry loops

        checkpoint.has_more = False
        return checkpoint

    # ==================== API Methods ====================

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
                return None
            logger.exception(
                f"Error fetching blocks with status code {res.status_code}: {res.json()}"
            )
            return None
        return res.json()

    # ==================== Content Processing ====================

    def _discover_child_pages(self, page_id: str) -> list[str]:
        """Discover child pages and database rows from a page.

        Returns list of page IDs found in:
        - Child pages (nested pages)
        - Child databases (databases embedded in the page)
        - Database rows (pages within databases)
        """
        child_page_ids: list[str] = []

        # Discover from blocks (child pages and databases)
        blocks_data = self._fetch_child_blocks(page_id)
        if blocks_data:
            for block in blocks_data.get("results", []):
                block_type = block.get("type")

                if block_type == "child_page":
                    child_page_ids.append(block["id"])
                elif block_type == "child_database":
                    database_id = block["id"]
                    # Discover pages from all data sources in the database
                    child_page_ids.extend(
                        self._discover_pages_from_database(database_id)
                    )

        # Also check if this page is a database and discover its rows
        # (We need to try fetching as database to check)
        try:
            data_source_ids = self._get_database_data_sources(page_id)
            if data_source_ids:
                child_page_ids.extend(self._discover_pages_from_database(page_id))
        except Exception:
            # Not a database, that's fine
            pass

        return child_page_ids

    def _discover_pages_from_database(self, database_id: str) -> list[str]:
        """Discover all page IDs from a database's data sources."""
        page_ids: list[str] = []
        data_source_ids = self._get_database_data_sources(database_id)

        if not data_source_ids:
            return page_ids

        # Query all data sources
        for data_source_id in data_source_ids:
            cursor = None
            while True:
                data = self._fetch_data_source_query(data_source_id, cursor)

                for result in data.get("results", []):
                    obj_type = result.get("object")
                    if obj_type == "page":
                        page_ids.append(result["id"])
                    elif obj_type == "database":
                        # Nested database - recurse
                        page_ids.extend(
                            self._discover_pages_from_database(result["id"])
                        )

                if data.get("next_cursor"):
                    cursor = data["next_cursor"]
                else:
                    break

        return page_ids

    def _read_blocks(self, page_id: str) -> list[NotionBlock]:
        """Read all blocks from a page and convert to NotionBlock objects."""
        blocks: list[NotionBlock] = []
        cursor = None

        while True:
            data = self._fetch_child_blocks(page_id, cursor)
            if data is None:
                break

            for result in data.get("results", []):
                result_type = result.get("type")
                result_obj = result.get(result_type, {})

                # Skip unsupported block types
                if result_type in (
                    "ai_block",
                    "unsupported",
                    "external_object_instance_page",
                ):
                    logger.debug(f"Skipping unsupported block type '{result_type}'")
                    continue

                # Extract text content
                text_parts = []
                if "rich_text" in result_obj:
                    for rich_text in result_obj["rich_text"]:
                        if "text" in rich_text:
                            text_parts.append(rich_text["text"]["content"])

                if text_parts:
                    blocks.append(
                        NotionBlock(
                            id=result["id"],
                            text="\n".join(text_parts),
                            prefix="\n",
                        )
                    )

                # Recursively read nested blocks (except child pages which are separate documents)
                if result.get("has_children") and result_type != "child_page":
                    nested_blocks = self._read_blocks(result["id"])
                    blocks.extend(nested_blocks)

            if data.get("next_cursor"):
                cursor = data["next_cursor"]
            else:
                break

        return blocks

    @staticmethod
    def _properties_to_str(properties: dict[str, Any]) -> str:
        """Convert Notion properties to a string representation."""

        def _recurse_list_properties(inner_list: list[Any]) -> str | None:
            list_properties: list[str | None] = []
            for item in inner_list:
                if item and isinstance(item, dict):
                    list_properties.append(_recurse_properties(item))
                elif item and isinstance(item, list):
                    list_properties.append(_recurse_list_properties(item))
                else:
                    list_properties.append(str(item))
            return ", ".join([p for p in list_properties if p]) or None

        def _recurse_properties(inner_dict: dict[str, Any]) -> str | None:
            sub_inner_dict: dict[str, Any] | list[Any] | str = inner_dict
            while isinstance(sub_inner_dict, dict) and "type" in sub_inner_dict:
                type_name = sub_inner_dict["type"]
                sub_inner_dict = sub_inner_dict[type_name]
                if not sub_inner_dict:
                    return None

            if isinstance(sub_inner_dict, list):
                return _recurse_list_properties(sub_inner_dict)
            elif isinstance(sub_inner_dict, str):
                return sub_inner_dict
            elif isinstance(sub_inner_dict, dict):
                if "name" in sub_inner_dict:
                    return sub_inner_dict["name"]
                if "content" in sub_inner_dict:
                    return sub_inner_dict["content"]
                start = sub_inner_dict.get("start")
                end = sub_inner_dict.get("end")
                if start is not None:
                    return f"{start} - {end}" if end is not None else start
                elif end is not None:
                    return f"Until {end}"
                if "id" in sub_inner_dict:
                    return None  # Skip ID references

            return None

        result = ""
        for prop_name, prop in properties.items():
            if not prop or not isinstance(prop, dict):
                continue
            try:
                inner_value = _recurse_properties(prop)
                if inner_value:
                    result += f"{prop_name}: {inner_value}\t"
            except Exception as e:
                logger.warning(f"Error recursing properties for {prop_name}: {e}")
                continue

        return result

    def _read_page_title(self, page: NotionPage) -> str | None:
        """Extract the title from a Notion page."""
        if page.database_name:
            return page.database_name
        for prop in page.properties.values():
            if prop.get("type") == "title" and prop.get("title"):
                return " ".join(
                    [t.get("plain_text", "") for t in prop["title"]]
                ).strip()
        return None

    def _page_to_document(self, page: NotionPage) -> Document | None:
        """Convert a NotionPage to a Document."""
        page_title = self._read_page_title(page) or f"Untitled Page with ID {page.id}"

        # Format properties
        properties_text = self._properties_to_str(page.properties)

        # Build metadata
        page_metadata: dict[str, str | list[str]] = {
            "notion_page_id": page.id,
            "notion_page_url": page.url,
            "created_time": page.created_time,
            "last_edited_time": page.last_edited_time,
            "archived": str(page.archived).lower(),
        }

        # Add property values to metadata
        if page.properties:
            for prop_name, prop in page.properties.items():
                if prop and isinstance(prop, dict):
                    prop_value = self._properties_to_str({prop_name: prop})
                    if prop_value:
                        prop_value_clean = prop_value.replace(
                            f"{prop_name}: ", ""
                        ).strip()
                        if prop_value_clean:
                            page_metadata[f"property_{prop_name}"] = prop_value_clean

        # Read page blocks
        page_blocks = self._read_blocks(page.id)

        # Build sections
        sections: list[TextSection | ImageSection] = []

        # Add properties section if exists
        if properties_text:
            sections.append(
                TextSection(
                    link=page.url,
                    text=properties_text.strip(),
                )
            )

        # Add content blocks
        if page_blocks:
            sections.extend(
                [
                    TextSection(
                        link=f"{page.url}#{block.id.replace('-', '')}",
                        text=block.prefix + block.text,
                    )
                    for block in page_blocks
                ]
            )
        elif not properties_text:
            # No content and no properties - skip this page
            logger.warning(
                f"No blocks or properties found for page with ID '{page.id}'. Skipping."
            )
            return None

        return Document(
            id=page.id,
            sections=cast(list[TextSection | ImageSection], sections),
            source=DocumentSource.NOTION,
            semantic_identifier=page_title,
            doc_updated_at=datetime.fromisoformat(
                page.last_edited_time.replace("Z", "+00:00")
            ).astimezone(timezone.utc),
            metadata=page_metadata,
        )

    # ==================== Validation ====================

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
                # Without root_page_id, we can't validate easily
                # Just check that credentials work by trying to list databases
                res = rl_requests.get(
                    "https://api.notion.com/v1/databases",
                    headers=self.headers,
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
