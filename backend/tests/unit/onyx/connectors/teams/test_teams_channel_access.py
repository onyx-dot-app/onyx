"""Channel readership: who a Teams channel's documents are shared with."""

from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.models import ConnectorFailure, Document
from onyx.connectors.teams.connector import _collect_documents_for_channel
from onyx.connectors.teams.utils import (
    channel_access,
    fetch_channel_members,
    fetch_channel_readers,
)

TEAM_ID = "team-1"
CHANNEL_ID = "19:channel@thread.tacv2"
SERVICE_ROOT = "https://graph.microsoft.com/v1.0"
MEMBERS_URL = f"teams/{TEAM_ID}/channels/{CHANNEL_ID}/allMembers"


def _response(status: int, payload: dict[str, Any]) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.ok = status < 400
    response.status_code = status
    response.headers = {}
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status}", response=response
        )
    return response


def _graph_client(
    routes: dict[str, dict[str, Any]], refused: dict[str, int] | None = None
) -> MagicMock:
    """A client whose direct requests answer from ``routes``, fail with the
    status in ``refused``, and 404 elsewhere. The SDK raises on every non-2xx
    status, so failures arrive as exceptions the way they do in production."""
    client = MagicMock()
    client.service_root_url.return_value = SERVICE_ROOT

    def execute(url: str) -> MagicMock:
        if url in routes:
            return _response(200, routes[url])
        status = (refused or {}).get(url, 404)
        response = _response(status, {"error": {"code": str(status)}})
        raise requests.HTTPError(str(status), response=response)

    client.execute_request_direct.side_effect = execute
    return client


def _member(name: str | None, email: str | None, user_id: str) -> dict[str, Any]:
    return {"displayName": name, "email": email, "userId": user_id}


def _message(message_id: str, text: str, reply_to: str | None = None) -> dict[str, Any]:
    return {
        "id": message_id,
        "replyToId": reply_to,
        "subject": None if reply_to else f"Subject {message_id}",
        "from": {"user": {"id": "u1", "displayName": "Ada"}},
        "body": {"contentType": "html", "content": f"<p>{text}</p>"},
        "createdDateTime": "2026-09-01T10:00:00Z",
        "lastModifiedDateTime": "2026-09-01T10:00:00Z",
        "lastEditedDateTime": None,
        "deletedDateTime": None,
        "webUrl": f"https://teams.example/{message_id}",
    }


def _standard_channel() -> MagicMock:
    channel = MagicMock()
    channel.id = CHANNEL_ID
    channel.membership_type = "standard"
    channel.properties = {"displayName": "General"}
    return channel


def _team() -> MagicMock:
    team = MagicMock()
    team.id = TEAM_ID
    return team


def test_members_are_read_from_every_page_of_the_all_members_call() -> None:
    client = _graph_client(
        {
            MEMBERS_URL: {
                "value": [_member("Ada", "ada@example.com", "u1")],
                "@odata.nextLink": f"{SERVICE_ROOT}/{MEMBERS_URL}?$skiptoken=p2",
            },
            f"{MEMBERS_URL}?$skiptoken=p2": {
                "value": [_member("Bob", "bob@partner.example", "u2")]
            },
        }
    )

    members = fetch_channel_members(client, TEAM_ID, CHANNEL_ID)

    assert [m.email for m in members] == ["ada@example.com", "bob@partner.example"]


def test_a_standard_channel_is_shared_with_its_members_not_everyone() -> None:
    client = _graph_client(
        {MEMBERS_URL: {"value": [_member("Ada", "Ada@Example.com", "u1")]}}
    )

    experts, access = fetch_channel_readers(client, TEAM_ID, CHANNEL_ID)

    assert [(e.display_name, e.email) for e in experts] == [("Ada", "Ada@Example.com")]
    assert access.is_public is False
    assert access.external_user_emails == {"ada@example.com"}
    assert access.external_user_group_ids == set()


def test_a_member_without_an_email_is_resolved_by_user_id() -> None:
    client = _graph_client(
        {
            MEMBERS_URL: {"value": [_member("Raunak", None, "u-raunak")]},
            "users/u-raunak": {"userPrincipalName": "raunak@example.com"},
        }
    )

    experts, _ = fetch_channel_readers(client, TEAM_ID, CHANNEL_ID)

    assert [(e.display_name, e.email) for e in experts] == [
        ("Raunak", "raunak@example.com")
    ]


def test_a_member_from_another_tenant_keeps_the_email_on_the_row() -> None:
    """Cross-tenant members of a shared channel cannot be looked up here, and
    they do not need to be: the all-members row carries their email. One whose
    row has none is not in this directory and is dropped."""
    client = _graph_client(
        {
            MEMBERS_URL: {
                "value": [
                    _member("Guest", "guest@other.example", "u-foreign"),
                    _member("Ghost", None, "u-gone"),
                ]
            }
        }
    )

    _, access = fetch_channel_readers(client, TEAM_ID, CHANNEL_ID)

    assert access.external_user_emails == {"guest@other.example"}
    assert client.execute_request_direct.call_args_list[-1].args == ("users/u-gone",)


def test_a_refused_user_lookup_is_not_a_missing_member() -> None:
    client = _graph_client(
        {MEMBERS_URL: {"value": [_member("Ada", None, "u1")]}},
        refused={"users/u1": 403},
    )

    with pytest.raises(requests.HTTPError):
        fetch_channel_readers(client, TEAM_ID, CHANNEL_ID)


def test_a_member_without_a_display_name_still_reads() -> None:
    client = _graph_client(
        {MEMBERS_URL: {"value": [_member(None, "x@example.com", "u1")]}}
    )

    experts, access = fetch_channel_readers(client, TEAM_ID, CHANNEL_ID)

    assert [(e.display_name, e.email) for e in experts] == [(None, "x@example.com")]
    assert access.external_user_emails == {"x@example.com"}


def test_a_channel_with_no_resolvable_members_is_shared_with_no_one() -> None:
    client = _graph_client({MEMBERS_URL: {"value": [_member(None, None, "")]}})

    _, access = fetch_channel_readers(client, TEAM_ID, CHANNEL_ID)

    assert access.is_public is False
    assert access.external_user_emails == set()


def test_channel_access_is_never_public() -> None:
    assert channel_access([]).is_public is False


def test_a_throttled_members_call_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK raises on a 429 instead of returning it, so the retry policy has
    to read the status off the exception."""
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    client = MagicMock()
    client.service_root_url.return_value = SERVICE_ROOT
    client.execute_request_direct.side_effect = [
        requests.HTTPError("429", response=_response(429, {})),
        _response(200, {"value": [_member("Ada", "ada@example.com", "u1")]}),
    ]

    members = fetch_channel_members(client, TEAM_ID, CHANNEL_ID)

    assert [m.email for m in members] == ["ada@example.com"]
    assert client.execute_request_direct.call_count == 2


def test_a_standard_channel_walk_shares_every_thread_with_the_members_once() -> None:
    delta_url = (
        f"teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages/delta"
        "?$filter=lastModifiedDateTime gt 1970-01-01T00:00:00Z"
    )
    client = _graph_client(
        {
            MEMBERS_URL: {"value": [_member("Ada", "ada@example.com", "u1")]},
            delta_url: {"value": [_message("m1", "first"), _message("m2", "second")]},
            f"teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages/m1/replies": {
                "value": [_message("r1", "reply", reply_to="m1")]
            },
            f"teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages/m2/replies": {"value": []},
        }
    )

    documents = [
        item
        for item in _collect_documents_for_channel(
            client, _team(), _standard_channel(), start=0
        )
        if isinstance(item, Document)
    ]

    assert len(documents) == 2
    for document in documents:
        assert document.external_access is not None
        assert document.external_access.is_public is False
        assert document.external_access.external_user_emails == {"ada@example.com"}
        assert [e.email for e in document.primary_owners or []] == ["ada@example.com"]
    member_calls = [
        call.args[0]
        for call in client.execute_request_direct.call_args_list
        if call.args[0] == MEMBERS_URL
    ]
    assert len(member_calls) == 1


def _assert_one_channel_failure(
    items: Sequence[Document | None | ConnectorFailure],
) -> None:
    assert len(items) == 1
    failure = items[0]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_entity is not None
    assert failure.failed_entity.entity_id == CHANNEL_ID


def test_a_channel_whose_members_are_refused_is_one_failure_not_a_crash() -> None:
    client = _graph_client({}, refused={MEMBERS_URL: 403})

    items = list(
        _collect_documents_for_channel(client, _team(), _standard_channel(), start=0)
    )

    _assert_one_channel_failure(items)


def test_a_channel_whose_members_stay_throttled_is_one_failure_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    client = MagicMock()
    client.service_root_url.return_value = SERVICE_ROOT
    client.execute_request_direct.side_effect = requests.HTTPError(
        "429", response=_response(429, {})
    )

    items = list(
        _collect_documents_for_channel(client, _team(), _standard_channel(), start=0)
    )

    _assert_one_channel_failure(items)
