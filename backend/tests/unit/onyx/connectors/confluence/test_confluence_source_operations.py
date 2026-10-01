from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
import requests
from atlassian.errors import ApiError

from onyx.connectors.confluence import source_operations
from onyx.connectors.confluence import utils as confluence_utils
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.confluence.source_operations import (
    ConfluenceProbeVariant,
    ConfluenceRetriesExhaustedError,
    ConfluenceSourceOperations,
    ConfluenceSpaceNotFoundError,
    _OnyxConfluence,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CredentialsProviderInterface
from tests.unit.onyx.connectors.confluence.confluence_gateway_fakes import (
    gateway_with_client,
)

_WIKI_BASE = "https://confluence.example.com"
_ATTACHMENT: dict[str, Any] = {
    "id": "att1",
    "title": "spec.pdf",
    "_links": {"download": "/download/attachments/1/spec.pdf"},
}


def _provider() -> mock.Mock:
    provider = mock.Mock(spec=CredentialsProviderInterface)
    provider.is_dynamic.return_value = False
    provider.get_credentials.return_value = {
        "confluence_username": "user",
        "confluence_access_token": "token",
    }
    provider.get_provider_key.return_value = "key"
    provider.__enter__ = mock.Mock(return_value=None)
    provider.__exit__ = mock.Mock(return_value=None)
    return provider


def _response(status_code: int, content: bytes = b"") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = content
    response.url = _WIKI_BASE
    return response


def _sdk_client(*responses: requests.Response) -> mock.Mock:
    sdk = mock.Mock()
    sdk.url = _WIKI_BASE
    sdk.session.get.side_effect = list(responses)
    return sdk


def _transport(sdk: mock.Mock, is_cloud: bool = False) -> _OnyxConfluence:
    client = _OnyxConfluence(
        is_cloud=is_cloud, url=_WIKI_BASE, credentials_provider=_provider()
    )
    client._confluence = sdk
    client._kwargs = client.shared_base_kwargs
    return client


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes retry waits instant: sleep advances a fake monotonic clock."""
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    fake_time = SimpleNamespace(monotonic=monotonic, sleep=sleep)
    monkeypatch.setattr(source_operations, "time", fake_time)
    monkeypatch.setattr(confluence_utils, "time", fake_time)


@pytest.mark.usefixtures("fake_clock")
def test_download_attachment_retries_server_errors() -> None:
    # Precondition.
    sdk = _sdk_client(_response(503), _response(200, b"file bytes"))
    gateway = gateway_with_client(_transport(sdk), wiki_base=_WIKI_BASE)

    # Under test.
    content = gateway.download_attachment(attachment=_ATTACHMENT, parent_content_id="1")

    # Postcondition.
    assert content == b"file bytes"
    assert sdk.session.get.call_count == 2
    sdk.session.get.assert_called_with(_WIKI_BASE + "/download/attachments/1/spec.pdf")


def test_download_attachment_uses_the_refreshed_client() -> None:
    # Precondition.
    stale_sdk = _sdk_client(_response(200, b"stale"))
    fresh_sdk = _sdk_client(_response(200, b"fresh"))
    client = _transport(stale_sdk)
    gateway = gateway_with_client(client, wiki_base=_WIKI_BASE)

    # Under test.
    with (
        mock.patch.object(
            client, "_renew_credentials", return_value=({"new": "creds"}, True)
        ),
        mock.patch.object(
            client, "_initialize_connection_helper", return_value=fresh_sdk
        ) as rebuild,
    ):
        content = gateway.download_attachment(
            attachment=_ATTACHMENT, parent_content_id="1"
        )

    # Postcondition.
    assert content == b"fresh"
    rebuild.assert_called_once()
    stale_sdk.session.get.assert_not_called()


def test_download_attachment_raises_on_client_error() -> None:
    # Precondition.
    sdk = _sdk_client(_response(404))
    gateway = gateway_with_client(_transport(sdk), wiki_base=_WIKI_BASE)

    # Under test / postcondition.
    with pytest.raises(requests.HTTPError):
        gateway.download_attachment(attachment=_ATTACHMENT, parent_content_id="1")
    assert sdk.session.get.call_count == 1


def test_download_attachment_does_not_retry_a_403() -> None:
    # Precondition.
    sdk = _sdk_client(_response(403), _response(200, b"file bytes"))
    gateway = gateway_with_client(_transport(sdk), wiki_base=_WIKI_BASE)

    # Under test / postcondition.
    with pytest.raises(requests.HTTPError) as raised:
        gateway.download_attachment(attachment=_ATTACHMENT, parent_content_id="1")
    assert raised.value.response is not None
    assert raised.value.response.status_code == 403
    assert sdk.session.get.call_count == 1


@pytest.mark.usefixtures("fake_clock")
def test_exhausted_retries_raise_with_the_last_status() -> None:
    # Precondition.
    client = _transport(_sdk_client())

    def always_rate_limited(_confluence: Any) -> bytes:
        response = _response(429)
        raise requests.HTTPError(response=response)

    # Under test / postcondition.
    with pytest.raises(ConfluenceRetriesExhaustedError) as raised:
        client._call_with_retries(always_rate_limited)
    assert raised.value.last_status_code == 429


def test_download_attachment_cloud_needs_parent_id() -> None:
    gateway = gateway_with_client(
        _transport(_sdk_client(), is_cloud=True), is_cloud=True
    )

    with pytest.raises(ValueError):
        gateway.download_attachment(attachment=_ATTACHMENT, parent_content_id=None)


@pytest.mark.parametrize("scoped_token", [False, True])
def test_connector_probes_the_site_once(scoped_token: bool) -> None:
    """One probe and one tenant_info lookup per connector, even though
    validation builds a second, low-timeout client."""
    # Precondition.
    connector = ConfluenceConnector(
        wiki_base=_WIKI_BASE, is_cloud=True, space="KEY", scoped_token=scoped_token
    )

    with (
        mock.patch.object(_OnyxConfluence, "_probe_connection") as probe,
        mock.patch.object(
            source_operations,
            "scoped_url",
            return_value="https://api.atlassian.com/ex/confluence/cloud-id",
        ) as resolve_scoped_url,
        mock.patch.object(
            ConfluenceSourceOperations,
            "list_spaces",
            return_value=iter([{"key": "KEY"}]),
        ),
        mock.patch.object(
            _OnyxConfluence, "get_space", create=True, return_value={"key": "KEY"}
        ),
    ):
        # Under test.
        connector.set_credentials_provider(_provider())
        connector.validate_connector_settings()

        # Postcondition.
        probe.assert_called_once()
        assert resolve_scoped_url.call_count == (1 if scoped_token else 0)
        gateway = connector.source_operations
        assert gateway._cached_client is not None
        assert gateway._cached_fast_client is not None
        assert gateway._cached_client is not gateway._cached_fast_client


def test_probe_site_rejects_a_mismatched_variant() -> None:
    gateway = ConfluenceSourceOperations(
        credentials_provider=_provider(),
        connector_specific_config={"wiki_base": _WIKI_BASE, "is_cloud": False},
    )

    with pytest.raises(ValueError):
        gateway.probe_site(variant=ConfluenceProbeVariant.SCOPED)


def test_get_space_translates_the_sdk_error() -> None:
    # Precondition.
    client = mock.Mock(spec=_OnyxConfluence)
    client.get_space = mock.Mock(side_effect=ApiError("no such space"))
    gateway = gateway_with_client(client)
    connector = ConfluenceConnector(wiki_base=_WIKI_BASE, is_cloud=False, space="X")
    connector._source_operations = gateway

    # Under test / postcondition.
    with pytest.raises(ConfluenceSpaceNotFoundError):
        gateway.get_space(space_key="X")
    client.retrieve_confluence_spaces.return_value = iter([{"key": "Y"}])
    with pytest.raises(ConnectorValidationError, match="Invalid Confluence space key"):
        connector.validate_connector_settings()
