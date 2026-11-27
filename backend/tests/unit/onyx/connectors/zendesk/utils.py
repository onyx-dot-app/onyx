from collections.abc import Callable
from typing import Any

from onyx.connectors.zendesk.connector import ZendeskConnector

CREDENTIALS: dict[str, Any] = {
    "zendesk_subdomain": "test",
    "zendesk_email": "test@example.com",
    "zendesk_token": "test_token",
}


def set_request_function(
    connector: ZendeskConnector,
    make_request: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> None:
    """Loads test credentials and replaces the gateway's request function, so
    tests answer each (endpoint, params) call."""
    connector.load_credentials(CREDENTIALS)
    connector.ops._request_cache = make_request
