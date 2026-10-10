"""Notion source-operations gateway: every Notion REST call lives here. Nothing
else under onyx/connectors/notion talks to Notion."""

from collections.abc import Callable
from typing import Any

import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.notion.models import NotionBotUser
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)

_API_BASE = "https://api.notion.com/v1"
_API_VERSION = "2026-03-11"
_TOKEN_KEY = "notion_integration_token"
_CALL_TIMEOUT_S = 30
_DEFAULT_WORKSPACE_NAME = "Notion Workspace"
_UNTESTED = "not yet tested during incremental migration"


class NotionGatewayError(Exception):
    """Base of the gateway's errors: a transport failure or an error status."""


class NotionTransportError(NotionGatewayError):
    """The request got no HTTP response: connection failure or timeout."""


class NotionApiError(NotionGatewayError):
    """Notion answered with an error status."""

    def __init__(self, status_code: int, body: Any, url: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Notion returned HTTP {status_code} for {url}: {body}")


def _response_body(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _json(response: requests.Response, url: str) -> dict[str, Any]:
    if not response.ok:
        raise NotionApiError(response.status_code, _response_body(response), url)
    return response.json()


class NotionSourceOperations(SourceOperations):
    source = DocumentSource.NOTION
    sdk_modules = ("requests",)
    config_keys = frozenset[str]()

    # The provider may read the DB on every call, so the token is read once.
    _cached_headers: dict[str, str] | None = None

    def _headers(self) -> dict[str, str]:
        if self._cached_headers is None:
            token: str | None = self.credentials_provider.get_credentials().get(
                _TOKEN_KEY
            )
            if not token:
                raise ConnectorMissingCredentialError("Notion")
            self._cached_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": _API_VERSION,
            }
        return self._cached_headers

    def _request(
        self, method: Callable[..., requests.Response], path: str, **kwargs: Any
    ) -> dict[str, Any]:
        url: str = f"{_API_BASE}/{path}"
        try:
            response: requests.Response = method(
                url, headers=self._headers(), timeout=_CALL_TIMEOUT_S, **kwargs
            )
        except requests.exceptions.RequestException as error:
            raise NotionTransportError(str(error)) from error
        return _json(response, url)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_bot_user(self) -> NotionBotUser:
        data: dict[str, Any] = self._request(rl_requests.get, "users/me")
        bot: dict[str, Any] = data.get("bot", {})
        # Bot users without a workspace_id key the workspace by the user id.
        return NotionBotUser(
            workspace_id=bot.get("workspace_id") or data["id"],
            workspace_name=bot.get("workspace_name") or _DEFAULT_WORKSPACE_NAME,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def search(self, *, query: dict[str, Any]) -> dict[str, Any]:
        return self._request(rl_requests.post, "search", json=query)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_page(self, *, page_id: str) -> dict[str, Any]:
        return self._request(rl_requests.get, f"pages/{page_id}")

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_database(self, *, database_id: str) -> dict[str, Any]:
        return self._request(rl_requests.get, f"databases/{database_id}")

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def query_data_source(
        self, *, data_source_id: str, cursor: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            rl_requests.post,
            f"data_sources/{data_source_id}/query",
            json={"start_cursor": cursor} if cursor else None,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_block_children(
        self, *, block_id: str, cursor: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            rl_requests.get,
            f"blocks/{block_id}/children",
            params={"start_cursor": cursor} if cursor else None,
        )
