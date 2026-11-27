from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import HTTPError

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.zendesk.connector import ZendeskConnector
from onyx.connectors.zendesk.source_operations import (
    ZendeskSourceOperations,
    subdomain_from_credential,
)
from tests.unit.onyx.connectors.zendesk.utils import (
    CREDENTIALS,
    set_request_function,
)


def _response(status_code: int, payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = HTTPError(response=response)
    return response


def _gateway() -> ZendeskSourceOperations:
    return ZendeskSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, DocumentSource.ZENDESK.value, CREDENTIALS
        )
    )


@pytest.mark.parametrize(
    "value",
    [
        "acme",
        "acme.zendesk.com",
        "https://acme.zendesk.com",
        "http://acme.zendesk.com/",
        "https://www.acme.zendesk.com/hc/en-us",
    ],
)
def test_subdomain_from_credential(value: str) -> None:
    assert subdomain_from_credential(value) == "acme"


def test_client_errors_are_not_retried() -> None:
    with patch(
        "onyx.connectors.zendesk.source_operations.requests.get",
        return_value=_response(401, {"error": "Couldn't authenticate you"}),
    ) as get:
        with pytest.raises(CredentialExpiredError):
            _gateway().get_me()
    assert get.call_count == 1


def test_server_errors_are_retried() -> None:
    with (
        patch(
            "onyx.connectors.zendesk.source_operations.requests.get",
            side_effect=[_response(503, {}), _response(200, {"user": {"id": 1}})],
        ) as get,
        patch("time.sleep"),
    ):
        assert _gateway().get_me().id == 1
    assert get.call_count == 2


def test_anonymous_user_is_a_credential_error() -> None:
    gateway = _gateway()
    gateway._request_cache = lambda _endpoint, _params: {"user": {"id": None}}
    with pytest.raises(CredentialExpiredError):
        gateway.get_me()


@pytest.mark.parametrize(
    "content_type, endpoint",
    [("articles", "help_center/articles"), ("tickets", "incremental/tickets.json")],
)
def test_validate_connector_settings_probes_the_content_type(
    content_type: str, endpoint: str
) -> None:
    make_request = MagicMock(
        return_value={
            "articles": [],
            "tickets": [],
            "meta": {"has_more": False},
            "end_time": 1,
            "end_of_stream": True,
        }
    )
    connector = ZendeskConnector(content_type=content_type)
    set_request_function(connector, make_request)
    connector.validate_connector_settings()
    assert [c.args[0] for c in make_request.call_args_list] == [endpoint]
