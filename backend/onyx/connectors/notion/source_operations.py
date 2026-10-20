"""The Notion source-operations gateway: every Notion API call goes through here.

Onyx calls the Notion REST API with ``requests``, and this is the only module in
``notion/`` that imports it. Operations return the raw JSON of the API, or
``NotionSearchResponse`` pages for a search. An error response, a network
error, or a rate limit leaves the gateway as ``NotionApiError``, so callers
never handle ``requests`` exceptions. The error carries the request and the
response body, for a check's Error Details.

Notion answers 404 ``object_not_found`` both for an object that does not exist
and for an object that is not shared with the integration.

By default an operation waits out rate limits, as indexing always did: it waits
the ``Retry-After`` time of each 429, at most 30 times. A ``fast=True`` call does
not wait and does not retry, so a 429 raises at once. The capability checks
use ``fast=True``, so a rate limit does not hold a check thread.
"""

from collections.abc import Iterator
from typing import Any

import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    RateLimitTriedTooManyTimesError,
    rl_requests,
)
from onyx.connectors.exceptions import SourceApiError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.notion.models import NotionSearchObjectType, NotionSearchResponse
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

NOTION_INTEGRATION_TOKEN_KEY = "notion_integration_token"
NOTION_API_VERSION = "2026-03-11"

_NOTION_API_URL = "https://api.notion.com/v1"
_NOTION_CALL_TIMEOUT = 30  # seconds
_NOTION_PAGE_SIZE = 100
_RATE_LIMITED_STATUS = 429
_ERROR_TEXT_CHARS = 300


class NotionApiError(SourceApiError):
    """A Notion API call failed.

    ``status_code`` is None for a network error; ``timed_out`` marks one
    where Notion did not answer in time. ``code`` is Notion's error code
    (e.g. ``unauthorized``, ``restricted_resource``, ``object_not_found``,
    ``rate_limited``), None when the response has none.
    ``retry_after_seconds`` is the ``Retry-After`` time of a 429.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        code: str | None,
        retry_after_seconds: float | None = None,
        timed_out: bool = False,
        method: str | None = None,
        url: str | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(
            message, status_code=status_code, method=method, url=url, body=body
        )
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        self.timed_out = timed_out

    @property
    def is_rate_limited(self) -> bool:
        return self.status_code == _RATE_LIMITED_STATUS


def _error_from_response(
    response: requests.Response, *, method: str, url: str
) -> NotionApiError:
    status: int = response.status_code
    code: str | None = None
    message: str | None = None
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        raw_code: Any = body.get("code")
        raw_message: Any = body.get("message")
        code = raw_code if isinstance(raw_code, str) else None
        message = raw_message if isinstance(raw_message, str) else None
    if message is None:
        message = (response.text or "")[:_ERROR_TEXT_CHARS]
    retry_after: float | None = (
        parse_retry_after_seconds(response.headers.get("Retry-After"))
        if status == _RATE_LIMITED_STATUS
        else None
    )
    return NotionApiError(
        f"Notion API error (HTTP {status}, {code}): {message}",
        status_code=status,
        code=code,
        retry_after_seconds=retry_after,
        method=method,
        url=url,
        body=response.text or None,
    )


class NotionSourceOperations(SourceOperations):
    source = DocumentSource.NOTION
    sdk_modules = ("requests",)
    # The gateway reads only the credential.
    config_keys = frozenset()

    def _headers(self) -> dict[str, str]:
        credentials: dict[str, Any] = self.credentials_provider.get_credentials()
        token: Any = credentials.get(NOTION_INTEGRATION_TOKEN_KEY)
        if not token:
            raise ConnectorMissingCredentialError("Notion")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_API_VERSION,
        }

    def _send(
        self,
        method: str,
        path: str,
        *,
        fast: bool,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One API request. Returns the JSON body; raises ``NotionApiError``."""
        url: str = f"{_NOTION_API_URL}/{path}"
        headers: dict[str, str] = self._headers()
        try:
            if fast:
                response: requests.Response = requests.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=_NOTION_CALL_TIMEOUT,
                )
            elif method == "GET":
                response = rl_requests.get(
                    url, headers=headers, params=params, timeout=_NOTION_CALL_TIMEOUT
                )
            else:
                response = rl_requests.post(
                    url, headers=headers, json=json_body, timeout=_NOTION_CALL_TIMEOUT
                )
        except RateLimitTriedTooManyTimesError as e:
            raise NotionApiError(
                f"Notion rate limited every attempt: {e}",
                status_code=_RATE_LIMITED_STATUS,
                code="rate_limited",
                method=method,
                url=url,
            ) from e
        except requests.RequestException as e:
            raise NotionApiError(
                f"Notion request failed: {e}",
                status_code=None,
                code=None,
                timed_out=isinstance(e, requests.Timeout),
                method=method,
                url=url,
            ) from e
        if response.status_code >= 400:
            raise _error_from_response(response, method=method, url=url)
        try:
            body: Any = response.json()
        except ValueError as e:
            raise NotionApiError(
                f"Notion returned a body that is not JSON (HTTP {response.status_code})",
                status_code=response.status_code,
                code=None,
                method=method,
                url=url,
                body=response.text or None,
            ) from e
        if not isinstance(body, dict):
            raise NotionApiError(
                f"Notion returned a JSON body that is not an object "
                f"(HTTP {response.status_code})",
                status_code=response.status_code,
                code=None,
                method=method,
                url=url,
                body=response.text or None,
            )
        return body

    def _search_page(self, query: dict[str, Any], fast: bool) -> NotionSearchResponse:
        logger.debug("Searching Notion with query: %s", query)
        return NotionSearchResponse(
            **self._send("POST", "search", fast=fast, json_body=query)
        )

    @retry_builder(tries=3, delay=1, backoff=2)
    def _search_page_with_retries(self, query: dict[str, Any]) -> NotionSearchResponse:
        return self._search_page(query, fast=False)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_bot_user(self, *, fast: bool = False) -> dict[str, Any]:
        """Returns the bot user of the token (``users/me``), with its
        workspace."""
        return self._send("GET", "users/me", fast=fast)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def iter_search(
        self,
        *,
        object_type: NotionSearchObjectType,
        sort_by_last_edited: bool = False,
        page_size: int = _NOTION_PAGE_SIZE,
        fast: bool = False,
    ) -> Iterator[NotionSearchResponse]:
        """Yields the result pages of a search for every object of one type
        that is shared with the integration. ``sort_by_last_edited`` sorts the
        newest first. Each page is fetched when the caller asks for it, and an
        error leaves as ``NotionApiError`` from the iteration. A page is tried
        3 times unless ``fast``."""
        query: dict[str, Any] = {
            "filter": {"property": "object", "value": object_type.value},
            "page_size": page_size,
        }
        if sort_by_last_edited:
            query["sort"] = {"timestamp": "last_edited_time", "direction": "descending"}
        cursor: str | None = None
        while True:
            page_query: dict[str, Any] = (
                {**query, "start_cursor": cursor} if cursor else query
            )
            page: NotionSearchResponse = (
                self._search_page(page_query, fast=True)
                if fast
                else self._search_page_with_retries(page_query)
            )
            yield page
            if not page.has_more:
                return
            cursor = page.next_cursor

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_page(self, *, page_id: str, fast: bool = False) -> dict[str, Any]:
        """Returns one page. A page that became a wiki is a database: Notion
        then answers 404."""
        logger.debug("Fetching page for ID '%s'", page_id)
        return self._send("GET", f"pages/{page_id}", fast=fast)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_database(self, *, database_id: str, fast: bool = False) -> dict[str, Any]:
        """Returns one database with its ``data_sources``. Since API version
        2025-09-03, the property schema is on the data sources."""
        logger.debug("Fetching database for ID '%s'", database_id)
        return self._send("GET", f"databases/{database_id}", fast=fast)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_block_children(
        self,
        *,
        block_id: str,
        start_cursor: str | None = None,
        page_size: int | None = None,
        fast: bool = False,
    ) -> dict[str, Any]:
        """Returns one page of the child blocks of a block or page."""
        logger.debug("Fetching children of block with ID '%s'", block_id)
        params: dict[str, Any] = {}
        if start_cursor:
            params["start_cursor"] = start_cursor
        if page_size is not None:
            params["page_size"] = page_size
        return self._send(
            "GET", f"blocks/{block_id}/children", fast=fast, params=params or None
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def query_data_source(
        self,
        *,
        data_source_id: str,
        start_cursor: str | None = None,
        page_size: int | None = None,
        fast: bool = False,
    ) -> dict[str, Any]:
        """Returns one page of the rows of a data source."""
        logger.debug("Querying data source '%s'", data_source_id)
        body: dict[str, Any] = {}
        if start_cursor:
            body["start_cursor"] = start_cursor
        if page_size is not None:
            body["page_size"] = page_size
        return self._send(
            "POST",
            f"data_sources/{data_source_id}/query",
            fast=fast,
            json_body=body or None,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_users(
        self,
        *,
        start_cursor: str | None = None,
        page_size: int = _NOTION_PAGE_SIZE,
        fast: bool = False,
    ) -> dict[str, Any]:
        """Returns one page of the users of the workspace. Notion answers 403
        when the integration does not have a user information capability."""
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return self._send("GET", "users", fast=fast, params=params)
