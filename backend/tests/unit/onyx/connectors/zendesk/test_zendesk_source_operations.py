from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import HTTPError

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.zendesk.connector import ZendeskConnector
from onyx.connectors.zendesk.source_operations import (
    ZendeskRequestError,
    ZendeskSourceOperations,
    subdomain_from_credential,
)
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector
from tests.unit.onyx.connectors.zendesk.utils import (
    CREDENTIALS,
    set_request_function,
)


def _response(status_code: int, payload: Any) -> MagicMock:
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


def test_anonymous_user_is_a_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = ZendeskConnector()
    set_request_function(
        monkeypatch, connector, lambda _endpoint, _params: {"user": {"id": None}}
    )
    with pytest.raises(CredentialExpiredError):
        connector.ops.get_me()


@pytest.mark.parametrize(
    "content_type, endpoint",
    [("articles", "help_center/articles"), ("tickets", "incremental/tickets.json")],
)
def test_validate_connector_settings_probes_the_content_type(
    monkeypatch: pytest.MonkeyPatch, content_type: str, endpoint: str
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
    set_request_function(monkeypatch, connector, make_request)
    connector.validate_connector_settings()
    assert [c.args[0] for c in make_request.call_args_list] == [endpoint]


def test_ticket_comments_follow_the_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {"comments": [{"id": 1}], "meta": {"has_more": True, "after_cursor": "c1"}},
        {"comments": [{"id": 2}], "meta": {"has_more": False}},
    ]
    make_request = MagicMock(side_effect=pages)
    connector = ZendeskConnector(content_type="tickets")
    set_request_function(monkeypatch, connector, make_request)

    comments = connector.ops.list_ticket_comments(ticket_id=5)

    assert [comment["id"] for comment in comments] == [1, 2]
    second_params = make_request.call_args_list[1].args[1]
    assert second_params["page[after]"] == "c1"


def test_a_cursor_that_does_not_advance_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"comments": [{"id": 1}], "meta": {"has_more": True, "after_cursor": "c1"}}
    connector = ZendeskConnector(content_type="tickets")
    set_request_function(monkeypatch, connector, MagicMock(return_value=page))

    with pytest.raises(ZendeskRequestError):
        connector.ops.list_ticket_comments(ticket_id=5)


def test_ticket_indexing_reads_no_content_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Support-only account has no Help Center to read content tags from."""
    make_request = MagicMock(
        return_value={"tickets": [], "end_of_stream": True, "end_time": 1}
    )
    connector = ZendeskConnector(content_type="tickets")
    set_request_function(monkeypatch, connector, make_request)

    load_everything_from_checkpoint_connector(connector, 0, 2_000_000_000)

    assert all(
        c.args[0] == "incremental/tickets.json" for c in make_request.call_args_list
    )


@pytest.mark.parametrize(
    "status_code, payload, expected",
    [
        (200, {"article": {"id": 7}}, True),
        # A sign-in or landing page served with 200.
        (200, {"something": "else"}, False),
        (200, {"article": None}, False),
        (200, [1, 2], False),
        (302, {}, False),
        (403, {}, False),
    ],
)
def test_is_article_public(status_code: int, payload: Any, expected: bool) -> None:
    with patch(
        "onyx.connectors.zendesk.source_operations.requests.Session.get",
        return_value=_response(status_code, payload),
    ) as get:
        assert _gateway().is_article_public(article_id=7) is expected
    assert get.call_args.kwargs["allow_redirects"] is False


def test_is_article_public_sends_no_netrc_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe must stay anonymous, but keep the environment's proxy and CA
    settings, so it disables only the netrc lookup."""
    import requests

    sent: list[requests.PreparedRequest] = []

    def send(
        _self: requests.Session, request: requests.PreparedRequest, **_kwargs: Any
    ) -> MagicMock:
        sent.append(request)
        return _response(403, {})

    monkeypatch.setattr(
        requests.sessions, "get_netrc_auth", lambda *_a, **_k: ("user", "secret")
    )
    monkeypatch.setattr(requests.Session, "send", send)
    assert _gateway().is_article_public(article_id=7) is False
    assert "Authorization" not in sent[0].headers
