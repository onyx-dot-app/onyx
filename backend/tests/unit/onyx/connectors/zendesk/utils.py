from collections.abc import Callable
from typing import Any

import pytest

import onyx.connectors.zendesk.source_operations as zendesk_source_operations
from onyx.connectors.zendesk.connector import ZendeskConnector

CREDENTIALS: dict[str, Any] = {
    "zendesk_subdomain": "test",
    "zendesk_email": "test@example.com",
    "zendesk_token": "test_token",
}

RequestFunction = Callable[[str, dict[str, Any]], dict[str, Any]]


def set_request_function(
    monkeypatch: pytest.MonkeyPatch,
    connector: ZendeskConnector,
    make_request: RequestFunction,
) -> None:
    """Loads test credentials and has the gateway send every request to
    make_request(endpoint, params)."""

    def build(*_args: Any, **_kwargs: Any) -> RequestFunction:
        return make_request

    monkeypatch.setattr(zendesk_source_operations, "_make_request_function", build)
    connector.load_credentials(CREDENTIALS)
