"""Builds a SharePoint gateway around fakes for the connector unit tests.

Connector tests stub whole operations with ``stub_operation``. Gateway tests
hand ``fake_gateway`` a ``get_json`` so the real operations run against a fake
Graph transport, or an ``sdk_client`` in place of the office365 client.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.microsoft_utils.graph_gateway import MicrosoftGraphGateway
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.source_operations import (
    CONFIG_SITES,
    SharepointSourceOperations,
)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
FAKE_TOKEN = "fake-token"
FAKE_CREDENTIALS = {
    "sp_client_id": "fake-client-id",
    "sp_directory_id": "fake-directory-id",
    "sp_client_secret": "fake-client-secret",
}

GetJson = Callable[[str, dict[str, str] | None], dict[str, Any]]


def _unexpected_call(url: str, params: dict[str, str] | None) -> dict[str, Any]:
    raise AssertionError(f"Unexpected Graph call: {url} {params}")


class FakeGraphApi(GraphApiClient):
    """The raw Graph client answering from a test function."""

    def __init__(self, get_json: GetJson) -> None:
        super().__init__(lambda: FAKE_TOKEN, GRAPH_API_BASE)
        self._fake_get_json = get_json

    def get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,  # noqa: ARG002
    ) -> dict[str, Any]:
        return self._fake_get_json(url, params)


def fake_gateway(
    *,
    sites: list[str] | None = None,
    get_json: GetJson | None = None,
    sdk_client: Any = None,
) -> SharepointSourceOperations:
    """A gateway over a static credential. With ``get_json`` the Graph
    transport is faked and no token is ever acquired. Without it the real
    Microsoft Graph gateway stays, for tests that patch the auth layer."""
    gateway = SharepointSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, "sharepoint", FAKE_CREDENTIALS
        ),
        connector_specific_config={CONFIG_SITES: list(sites or [])},
    )
    if get_json is not None:
        graph: Any = MagicMock(spec=MicrosoftGraphGateway)
        graph.graph_api_base = GRAPH_API_BASE
        graph.client = FakeGraphApi(get_json)
        graph.get_json.side_effect = graph.client.get_json
        graph.access_token.return_value = FAKE_TOKEN
        graph.token_response.return_value = {
            "access_token": FAKE_TOKEN,
            "expires_in": 3600,
        }
        gateway._graph_gateway = graph
    if sdk_client is not None:
        gateway._sdk_client = sdk_client
    return gateway


def connector_with_gateway(
    connector: SharepointConnector,
    *,
    get_json: GetJson | None = None,
    sdk_client: Any = None,
) -> SharepointSourceOperations:
    """Attaches a fake gateway to the connector and returns it for stubbing.
    Every raw Graph call fails loudly unless ``get_json`` answers it. Pass
    ``sdk_client`` for SDK reads."""
    gateway = fake_gateway(
        sites=connector.sites,
        get_json=get_json or _unexpected_call,
        sdk_client=sdk_client,
    )
    connector._ops = gateway
    return gateway


def stub_operation(
    gateway: SharepointSourceOperations, name: str, implementation: Callable[..., Any]
) -> None:
    """Replaces one operation on this gateway instance. The implementation
    takes the operation's keyword arguments."""
    setattr(gateway, name, implementation)
