from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import Optional

import requests
from pydantic import BaseModel
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
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NOTION_PAGE_SIZE = 100
_NOTION_CALL_TIMEOUT = 30  # 30 seconds


class NotionPage(BaseModel):
    """Represents a Notion Page object"""

    id: str
    created_time: str
    last_edited_time: str
    archived: bool
    properties: dict[str, Any]
    url: str

    database_name: str | None = None  # Only applicable to the database type page (wiki)


class NotionBlock(BaseModel):
    """Represents a Notion Block object"""

    id: str  # Used for the URL
    text: str
    prefix: str


class NotionSearchResponse(BaseModel):
    """Represents the response from the Notion Search API"""

    results: list[dict[str, Any]]
    next_cursor: Optional[str]
    has_more: bool = False


class NotionConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        recursive_index_enabled: bool = not NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP,
        root_page_id: str | None = None,
    ) -> None:
        self.batch_size = batch_size
        self.headers = {
            "Content-Type": "application/json",
            "Notion-Version": "2025-09-03",  # Updated API version
        }
        self.indexed_pages: set[str] = set()
        self.root_page_id = root_page_id
        self.recursive_index_enabled = recursive_index_enabled or self.root_page_id

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_child_blocks(
        self, block_id: str, cursor: str | None = None
    ) -> dict[str, Any] | None:
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
                    f"Likely not shared with integration. Exception:\n\n{e}"
                )
            else:
                logger.exception(
                    f"Error fetching blocks with status code {res.status_code}: {res.json()}"
                )
            return None
        return res.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_page(self, page_id: str) -> NotionPage:
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
            return self._fetch_database_as_page(page_id)
        return NotionPage(**res.json())

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_database_as_page(self, database_id: str) -> NotionPage:
        logger.debug(f"Fetching database for ID '{database_id}' as a page")
        database_url = f"https://api.notion.com/v1/databases/{database_id}"
        res = rl_requests.get(
            database_url,
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            logger.exception(f"Error fetching database as page - {res.json()}")
            raise e
        database_name = res.json().get("title")
        database_name = (
            database_name[0].get("text", {}).get("content") if database_name else None
        )
        return NotionPage(**res.json(), database_name=database_name)

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_data_sources(
        self, database_id: str
    ) -> list[dict[str, Any]]:
        """Fetch data sources for the given database."""
        logger.debug(f"Fetching data sources for database ID '{database_id}'")
        url = f"https://api.notion.com/v1/databases/{database_id}"
        res = rl_requests.get(
            url,
            headers=self.headers,
            timeout=_NOTION_CALL_TIMEOUT,
        )
        try:
            res.raise_for_status()
        except Exception as e:
            logger.exception(f"Error fetching data sources for database - {res.json()}")
            raise e
        json_data = res.json()
        # New field data_sources is a list of data source objects
        data_sources = json_data.get("data_sources")
        if not data_sources:
            # Fallback: treat the database itself as a single data source with its id
            logger.debug(f"No data_sources field, treating database ID as single data source")
            return [{"id": database_id}]
        return data_sources

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_database(
        self, database_id: str, cursor: str | None = None, data_source_id: str | None = None
    ) -> dict[str, Any]:
        logger.debug(
            f"Fetching database query for ID '{database_id}'"
            f"{' with data_source_id ' + data_source_id if data_source_id else ''}"
        )
        block_url = f"https://api.notion.com/v1/databases/{database_id}/query"
        body = None if not cursor else {"start_cursor": cursor}
        if data_source_id:
            if body is None:
                body = {}
            body["data_source_id"] = data_source_id
        res = rl_requests.post(
            block_url,
            headers=self.headers,
            json=body,
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
                    f"Likely not shared with integration. Exception:\n{e}"
                )
                return {"results": [], "next_cursor": None}
            logger.exception(f"Error fetching database - {res.json()}")
            raise e
        return res.json()
    
    @retry(tries=3, delay=1, backoff=2)
    def _search_notion(self, query: dict[str, Any]) -> NotionSearchResponse:
        logger.debug(f"Searching Notion with query: {query}")
        try:
            res = rl_requests.post(
                "https://api.notion.com/v1/search",
                headers=self.headers,
                json=query,
                timeout=_NOTION_CALL_TIMEOUT,
            )
            res.raise_for_status()
        except requests.exceptions.HTTPError as http_err:
            logger.warning(f"HTTP error during Notion search: {http_err}")
            if http_err.response.status_code == 400 and (
                "sort" in http_err.response.json().get("message", "")
                or "filter" in http_err.response.json().get("message", "")
            ):
                logger.warning(
                    "Invalid search parameters, removing sort/filter and trying again."
                )
                query.pop("sort", None)
                query.pop("filter", None)
                return self._search_notion(query)
            raise http_err
        except Exception as e:
            logger.exception(f"Error searching Notion: {e}")
            raise e
        return NotionSearchResponse(**res.json())

    def _properties_to_str(self, properties: dict[str, Any]) -> str:
        text_parts = []
        for prop_name, prop_data in properties.items():
            prop_type = prop_data.get("type")
            if prop_type == "title":
                if "title" in prop_data and prop_data["title"]:
                    text_parts.append(
                        f"Title: {''.join([t.get('plain_text', '') for t in prop_data['title']])}\n"
                    )
            elif prop_type == "rich_text":
                if "rich_text" in prop_data and prop_data["rich_text"]:
                    text_parts.append(
                        f"{prop_name}: {''.join([t.get('plain_text', '') for t in prop_data['rich_text']])}\n"
                    )
            elif prop_type == "url":
                if prop_data.get("url"):
                    text_parts.append(f"{prop_name}: {prop_data['url']}\n")
            elif prop_type == "multi_select":
                if prop_data.get("multi_select"):
                    options = [o.get("name", "") for o in prop_data["multi_select"]]
                    text_parts.append(f"{prop_name}: {', '.join(options)}\n")
            elif prop_type == "select":
                if prop_data.get("select"):
                    text_parts.append(f"{prop_name}: {prop_data['select']['name']}\n")
            # Add more property types as needed
        return "".join(text_parts)

    def _read_blocks(self, block_id: str) -> tuple[list[NotionBlock], list[str]]:
        blocks = []
        child_pages = []
        cursor = None
        while True:
            data = self._fetch_child_blocks(block_id, cursor)
            if not data or not data["results"]:
                break
            for result in data["results"]:
                block_type = result["type"]
                result_id = result["id"]
                prefix = ""
                text_content = ""

                if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
                    prefix = " "
                    rich_text_list = result[block_type].get("rich_text", [])
                    text_content = "".join([t["plain_text"] for t in rich_text_list])
                elif block_type == "bulleted_list_item":
                    prefix = "- "
                    rich_text_list = result[block_type].get("rich_text", [])
                    text_content = "".join([t["plain_text"] for t in rich_text_list])
                elif block_type == "numbered_list_item":
                    prefix = "1. "
                    rich_text_list = result[block_type].get("rich_text", [])
                    text_content = "".join([t["plain_text"] for t in rich_text_list])
                elif block_type == "page" or block_type == "child_page":
                    if self.recursive_index_enabled:
                        child_pages.append(result_id)
                    title = result["child_page"].get("title", "")
                    text_content = f"Page: {title}"
                elif block_type == "to_do":
                    prefix = "- [ ] "
                    rich_text_list = result[block_type].get("rich_text", [])
                    text_content = "".join([t["plain_text"] for t in rich_text_list])
                elif block_type == "toggle":
                    prefix = " "
                    rich_text_list = result[block_type].get("rich_text", [])
                    text_content = "".join([t["plain_text"] for t in rich_text_list])

                if text_content:
                    blocks.append(
                        NotionBlock(id=result_id, text=text_content, prefix=prefix)
                    )

            if not data["has_more"]:
                break
            cursor = data["next_cursor"]
        return blocks, child_pages

    def _read_page_title(self, page: NotionPage) -> str:
        if page.database_name:
            return page.database_name
        title = page.properties.get("title")
        if title and "title" in title and title["title"]:
            return "".join([t["plain_text"] for t in title["title"]])
        return ""

    def _filter_pages_by_time(
        self,
        pages: list[dict[str, Any]],
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        filter_field: str,
    ) -> list[NotionPage]:
        """Filters a list of Notion pages by a given time range."""
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        filtered_pages = []
        for page_data in pages:
            try:
                page = NotionPage(**page_data)
                last_edited_dt = datetime.fromisoformat(page.last_edited_time).replace(
                    tzinfo=timezone.utc
                )
                if start_dt <= last_edited_dt <= end_dt:
                    filtered_pages.append(page)
            except Exception as e:
                logger.warning(
                    f"Failed to parse page data or timestamp during filtering: {e}"
                )
        return filtered_pages

    def _read_pages_from_database(
        self, database_id: str
    ) -> tuple[list[NotionBlock], list[str]]:
        """Returns a list of top level blocks and all page IDs in the database,
        querying all data sources."""
        result_blocks: list[NotionBlock] = []
        result_pages: list[str] = []
        cursor = None

        data_sources = self._fetch_data_sources(database_id)
        if not data_sources:
            # fallback single query with no data_source_id
            data_sources = [{"id": database_id}]

        for data_source in data_sources:
            ds_id = data_source.get("id")
            ds_cursor = None
            while True:
                data = self._fetch_database(database_id, ds_cursor, data_source_id=ds_id)
                for result in data["results"]:
                    obj_id = result["id"]
                    obj_type = result["object"]
                    text = self._properties_to_str(result.get("properties", {}))
                    if text:
                        result_blocks.append(NotionBlock(id=obj_id, text=text, prefix="\n"))

                    if self.recursive_index_enabled:
                        if obj_type == "page":
                            logger.debug(
                                f"Found page with ID '{obj_id}' in database '{database_id}'"
                                f" data_source '{ds_id}'"
                            )
                            result_pages.append(result["id"])
                        elif obj_type == "database":
                            logger.debug(
                                f"Found database with ID '{obj_id}' in database '{database_id}'"
                                f" data_source '{ds_id}'"
                            )
                            _, child_pages = self._read_pages_from_database(obj_id)
                            result_pages.extend(child_pages)

                if data["next_cursor"] is None:
                    break
                ds_cursor = data["next_cursor"]

        return result_blocks, result_pages

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.headers["Authorization"] = (
            f'Bearer {credentials["notion_integration_token"]}'
        )
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
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

    def validate_connector_settings(self) -> None:
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
            )

    def _recursive_load(self) -> Generator[list[Document], None, None]:
        if self.root_page_id is None or not self.recursive_index_enabled:
            raise RuntimeError(
                "Recursive page lookup is not enabled, but we are trying to "
                "recursively load pages. This should never happen."
            )

        logger.info(
            "Recursively loading pages from Notion based on root page with "
            f"ID: {self.root_page_id}"
        )
        root_page = self._fetch_page(page_id=self.root_page_id)
        # BUG FIX: Calling the newly defined _read_pages method
        yield from batch_generator(self._read_pages([root_page]), self.batch_size)

    def _read_pages(self, pages: list[NotionPage]) -> Generator[Document, None, None]:
        """Reads content from a list of Notion pages and returns a generator of Documents."""
        for page in pages:
            if page.id in self.indexed_pages:
                continue
            self.indexed_pages.add(page.id)

            title = self._read_page_title(page)
            page_blocks, child_pages = self._read_blocks(page.id)

            content = self._properties_to_str(page.properties) + " " + " ".join(
                block.text for block in page_blocks
            )
            sections = [TextSection(text=content)]

            document = Document(
                source=DocumentSource.NOTION,
                document_id=page.id,
                title=title,
                content=content,
                source_url=page.url,
                created_at=datetime.fromisoformat(page.created_time).replace(
                    tzinfo=timezone.utc
                ),
                last_edited_at=datetime.fromisoformat(
                    page.last_edited_time
                ).replace(tzinfo=timezone.utc),
                sections=sections,
            )
            yield document

            if self.recursive_index_enabled and child_pages:
                # Recursively process child pages by fetching them first
                child_page_objects = [self._fetch_page(page_id) for page_id in child_pages]
                yield from self._read_pages(child_page_objects)


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