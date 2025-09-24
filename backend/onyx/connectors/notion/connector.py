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
_NOTION_API_VERSION = "2025-09-03"


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
            "Notion-Version": _NOTION_API_VERSION,
        }
        self.indexed_pages: set[str] = set()
        self.root_page_id = root_page_id
        self.recursive_index_enabled = recursive_index_enabled or self.root_page_id

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.headers["Authorization"] = (
            f'Bearer {credentials["notion_integration_token"]}'
        )
        return None

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_data_sources(self, database_id: str) -> list[dict[str, Any]]:
        """
        Fetch data sources for a database to support multi-source databases.
        Returns a list of data source objects.
        """
        url = f"https://api.notion.com/v1/databases/{database_id}"
        res = rl_requests.get(url, headers=self.headers, timeout=_NOTION_CALL_TIMEOUT)
        try:
            res.raise_for_status()
        except Exception as e:
            json_data = res.json()
            code = json_data.get("code")
            if code == "object_not_found":
                logger.error(
                    f"Unable to access database with ID '{database_id}' during data source fetch. "
                    f"Likely not shared with integration. Exception: {e}"
                )
                return []
            logger.exception(f"Error fetching database data sources - {json_data}")
            raise e

        json_resp = res.json()
        # New field introduced in 2025-09-03 for data_sources
        data_sources = json_resp.get("data_sources")
        if not data_sources:
            # Backwards compatibility fallback: treat the database itself as a single data source
            data_sources = [{"id": database_id}]
        return data_sources

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_database(
        self, database_id: str, data_source_id: str | None = None, cursor: str | None = None
    ) -> dict[str, Any]:
        """
        Fetch a database query results using data_source_id if provided.
        """
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        body = {}
        if cursor:
            body["start_cursor"] = cursor
        if data_source_id:
            body["data_source_id"] = data_source_id

        # If body is empty, send None for JSON to avoid sending empty JSON object
        json_body = body if body else None

        res = rl_requests.post(
            url,
            headers=self.headers,
            json=json_body,
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
                    f"Unable to access database with ID '{database_id}' "
                    f"or data source '{data_source_id}'. Possibly not shared. Exception: {e}"
                )
                return {"results": [], "next_cursor": None}
            logger.exception(f"Error fetching database - {json_data}")
            raise e
        return res.json()

    def _read_pages_from_database(
        self, database_id: str
    ) -> tuple[list[NotionBlock], list[str]]:
        """
        Returns a list of top level blocks and all page IDs in the database,
        supporting multi-source databases by querying each data source.
        """
        result_blocks: list[NotionBlock] = []
        result_pages: list[str] = []

        # Fetch all data sources for this database
        data_sources = self._fetch_data_sources(database_id)
        if not data_sources:
            logger.warning(f"No data sources found for database {database_id}")
            return result_blocks, result_pages

        for data_source in data_sources:
            data_source_id = data_source.get("id")
            cursor = None
            while True:
                data = self._fetch_database(database_id, data_source_id, cursor)

                for result in data["results"]:
                    obj_id = result["id"]
                    obj_type = result["object"]
                    text = self._properties_to_str(result.get("properties", {}))
                    if text:
                        result_blocks.append(NotionBlock(id=obj_id, text=text, prefix="\n"))

                    if self.recursive_index_enabled:
                        if obj_type == "page":
                            logger.debug(
                                f"Found page with ID '{obj_id}' in database '{database_id}' data source '{data_source_id}'"
                            )
                            result_pages.append(obj_id)
                        elif obj_type == "database":
                            logger.debug(
                                f"Found database with ID '{obj_id}' in database '{database_id}' data source '{data_source_id}'"
                            )
                            # Recursively read child database pages
                            _, child_pages = self._read_pages_from_database(obj_id)
                            result_pages.extend(child_pages)

                if data.get("next_cursor") is None:
                    break

                cursor = data.get("next_cursor")

        return result_blocks, result_pages

    # The rest of your methods remain mostly unchanged, except:
    # - Update _fetch_page and _fetch_database_as_page to use _NOTION_API_VERSION header
    # - Update _fetch_child_blocks to use new header version
    # - Update validate_connector_settings to use new header version

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
        json_resp = res.json()
        database_name = json_resp.get("title")
        database_name = (
            database_name[0].get("text", {}).get("content") if database_name else None
        )
        return NotionPage(**json_resp, database_name=database_name)

    # Keep the rest of your methods (_properties_to_str, _read_blocks, _read_pages, etc.) unchanged except update header version where applicable.

    def validate_connector_settings(self) -> None:
        if not self.headers.get("Authorization"):
            raise ConnectorMissingCredentialError("Notion credentials not loaded.")

        try:
            # Use new API version header for validation
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

    # The rest of your code (like _properties_to_str, _read_blocks, _read_pages, _search_notion, _filter_pages_by_time, _recursive_load, load_from_state, poll_source) remains unchanged except ensure the headers have the updated version.

# If you want me to provide the full unchanged parts as well, please let me know.

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