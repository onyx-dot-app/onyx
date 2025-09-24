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

    # ... Keep _properties_to_str, _read_blocks, _read_page_title unchanged ...

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

    # ... Keep _read_blocks and _read_pages unchanged (they call _read_pages_from_database) ...

    # Keep other methods unchanged except update headers "Notion-Version" to "2025-09-03"

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

    # Keep validate_connector_settings unchanged except update header version
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
        yield from batch_generator(self._read_pages([root_page]), self.batch_size)

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