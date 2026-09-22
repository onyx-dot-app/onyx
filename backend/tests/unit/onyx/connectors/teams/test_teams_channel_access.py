"""Channel readership: who a Teams channel's documents are shared with."""

from collections.abc import Sequence
from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.models import ConnectorFailure, Document
from onyx.connectors.teams import utils as utils_module
from onyx.connectors.teams.utils import (
    USER_LOOKUP_URL,
    GraphRetriesExhausted,
    UserDirectory,
    channel_access,
    fetch_channel_members,
    fetch_channel_readers,
)
from tests.unit.onyx.connectors.teams.helpers import (
    CHANNEL_ID,
    DELTA_URL,
    MEMBERS_URL,
    SERVICE_ROOT,
    TEAM_ID,
    connector,
    graph_client,
    member,
    message,
    replies_url,
    response,
    walk_channel,
)


def test_members_are_read_from_every_page_of_the_all_members_call() -> None:
    client = graph_client(
        {
            MEMBERS_URL: {
                "value": [member("Ada", "ada@example.com", "u1")],
                "@odata.nextLink": f"{SERVICE_ROOT}/{MEMBERS_URL}?$skiptoken=p2",
            },
            f"{MEMBERS_URL}?$skiptoken=p2": {
                "value": [member("Bob", "bob@partner.example", "u2")]
            },
        }
    )

    members = fetch_channel_members(client, TEAM_ID, CHANNEL_ID)

    assert [m.email for m in members] == ["ada@example.com", "bob@partner.example"]


def test_a_standard_channel_is_shared_with_its_members_not_everyone() -> None:
    client = graph_client(
        {MEMBERS_URL: {"value": [member("Ada", "Ada@Example.com", "u1")]}}
    )

    experts, access = fetch_channel_readers(
        client, TEAM_ID, CHANNEL_ID, UserDirectory(client)
    )

    assert [(e.display_name, e.email) for e in experts] == [("Ada", "Ada@Example.com")]
    assert access.is_public is False
    assert access.external_user_emails == {"ada@example.com"}
    assert access.external_user_group_ids == set()


def test_a_member_without_an_email_is_resolved_by_user_id() -> None:
    client = graph_client(
        {
            MEMBERS_URL: {"value": [member("Raunak", None, "u-raunak")]},
            USER_LOOKUP_URL: {"u-raunak": "raunak@example.com"},
        }
    )

    experts, _ = fetch_channel_readers(
        client, TEAM_ID, CHANNEL_ID, UserDirectory(client)
    )

    assert [(e.display_name, e.email) for e in experts] == [
        ("Raunak", "raunak@example.com")
    ]


def test_a_member_from_another_tenant_keeps_the_email_on_the_row() -> None:
    """Cross-tenant members of a shared channel cannot be looked up here, and
    they do not need to be: the all-members row carries their email. One whose
    row has none is not in this directory and is dropped."""
    client = graph_client(
        {
            MEMBERS_URL: {
                "value": [
                    member("Guest", "guest@other.example", "u-foreign"),
                    member("Ghost", None, "u-gone"),
                ]
            }
        }
    )

    _, access = fetch_channel_readers(
        client, TEAM_ID, CHANNEL_ID, UserDirectory(client)
    )

    assert access.external_user_emails == {"guest@other.example"}
    # Only the row without an email is asked about, and Graph does not name it.
    assert client.posted == [(USER_LOOKUP_URL, {"ids": ["u-gone"], "types": ["user"]})]


def test_a_refused_user_lookup_is_not_a_missing_member() -> None:
    client = graph_client(
        {MEMBERS_URL: {"value": [member("Ada", None, "u1")]}},
        refused={USER_LOOKUP_URL: 403},
    )

    with pytest.raises(requests.HTTPError):
        fetch_channel_readers(client, TEAM_ID, CHANNEL_ID, UserDirectory(client))


def test_a_member_without_a_display_name_still_reads() -> None:
    client = graph_client(
        {MEMBERS_URL: {"value": [member(None, "x@example.com", "u1")]}}
    )

    experts, access = fetch_channel_readers(
        client, TEAM_ID, CHANNEL_ID, UserDirectory(client)
    )

    assert [(e.display_name, e.email) for e in experts] == [(None, "x@example.com")]
    assert access.external_user_emails == {"x@example.com"}


def test_a_channel_with_no_resolvable_members_is_shared_with_no_one() -> None:
    client = graph_client({MEMBERS_URL: {"value": [member(None, None, "")]}})

    _, access = fetch_channel_readers(
        client, TEAM_ID, CHANNEL_ID, UserDirectory(client)
    )

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
        requests.HTTPError("429", response=response(429, {})),
        response(200, {"value": [member("Ada", "ada@example.com", "u1")]}),
    ]

    members = fetch_channel_members(client, TEAM_ID, CHANNEL_ID)

    assert [m.email for m in members] == ["ada@example.com"]
    assert client.execute_request_direct.call_count == 2


def test_a_standard_channel_walk_shares_every_thread_with_the_members_once() -> None:
    client = graph_client(
        {
            MEMBERS_URL: {"value": [member("Ada", "ada@example.com", "u1")]},
            DELTA_URL: {"value": [message("m1", "first"), message("m2", "second")]},
            replies_url("m1"): {"value": [message("r1", "reply", reply_to="m1")]},
            replies_url("m2"): {"value": []},
        }
    )

    documents = [
        item for item in walk_channel(connector(client)) if isinstance(item, Document)
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
    client = graph_client({}, refused={MEMBERS_URL: 403})

    _assert_one_channel_failure(walk_channel(connector(client)))


def test_a_channel_whose_members_stay_throttled_fails_the_attempt_not_the_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skipping the channel would drop its threads for good, so throttling that
    outlasts the retries fails the attempt and the checkpoint is retried."""
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    client = MagicMock()
    client.service_root_url.return_value = SERVICE_ROOT
    client.execute_request_direct.side_effect = requests.HTTPError(
        "429", response=response(429, {})
    )

    with pytest.raises(GraphRetriesExhausted):
        walk_channel(connector(client))


def _requested(client: MagicMock) -> list[str]:
    return [call.args[0] for call in client.execute_request_direct.call_args_list]


def test_members_without_an_email_are_named_a_batch_at_a_time_once_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A channel can hold thousands of mail-less members, so names come in
    # batches and once a run, not a request per member per channel.
    monkeypatch.setattr(utils_module, "USER_LOOKUP_BATCH_SIZE", 2)
    known = {"u1": "ada@example.com", "u2": "bob@example.com", "u3": "cy@example.com"}
    client = graph_client(
        {
            MEMBERS_URL: {"value": [member(uid, None, uid) for uid in known]},
            USER_LOOKUP_URL: known,
        }
    )
    directory = UserDirectory(client)

    for _ in range(2):
        _, access = fetch_channel_readers(client, TEAM_ID, CHANNEL_ID, directory)
        assert access.external_user_emails == set(known.values())

    # Two channels of the same three members: two batches, asked for once.
    assert [body["ids"] for _, body in client.posted] == [["u1", "u2"], ["u3"]]
    assert not [url for url in _requested(client) if url.startswith("users/")]


def test_an_id_graph_does_not_name_is_not_asked_for_again() -> None:
    client = graph_client(
        {
            MEMBERS_URL: {"value": [member("Ghost", None, "u-gone")]},
            USER_LOOKUP_URL: {},
        }
    )
    directory = UserDirectory(client)

    for _ in range(2):
        _, access = fetch_channel_readers(client, TEAM_ID, CHANNEL_ID, directory)
        assert access.external_user_emails == set()

    assert len(client.posted) == 1


def test_a_channel_whose_members_all_carry_an_email_asks_for_no_names() -> None:
    client = graph_client(
        {MEMBERS_URL: {"value": [member("Ada", "ada@example.com", "u1")]}}
    )

    fetch_channel_readers(client, TEAM_ID, CHANNEL_ID, UserDirectory(client))

    assert client.posted == []


def test_the_channel_walk_names_members_through_one_directory() -> None:
    client = graph_client(
        {
            MEMBERS_URL: {"value": [member("Ada", None, "u1")]},
            USER_LOOKUP_URL: {"u1": "ada@example.com"},
            DELTA_URL: {"value": [message("m1", "Plan")]},
            replies_url("m1"): {"value": []},
        }
    )
    teams_connector = connector(client)

    items = walk_channel(teams_connector)

    documents = [item for item in items if isinstance(item, Document)]
    assert documents[0].external_access is not None
    assert documents[0].external_access.external_user_emails == {"ada@example.com"}
    assert teams_connector.directory() is teams_connector.directory()
