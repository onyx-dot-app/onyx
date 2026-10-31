import re
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError

from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.google_chat import connector as google_chat_module
from onyx.connectors.google_chat.connector import GoogleChatConnector
from onyx.connectors.google_utils.resources import GoogleService
from onyx.connectors.models import ConnectorFailure, Document, SlimDocument
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

_ADMIN = "admin@acme.com"

# Directory users by id. Carol left the space, so Chat omits her display name.
_USERS: dict[str, dict[str, Any]] = {
    "1": {"primaryEmail": _ADMIN, "name": {"fullName": "Ada Admin"}},
    "2": {"primaryEmail": "bob@acme.com", "name": {"fullName": "Bob Builder"}},
    "3": {"primaryEmail": "carol@acme.com", "name": {"fullName": "Carol Coder"}},
    "4": {
        "primaryEmail": "dave@acme.com",
        "name": {"fullName": "Dave"},
        "suspended": True,
    },
    "5": {"primaryEmail": "erin@acme.com", "name": {"fullName": "Erin"}},
}

_SPACES: list[dict[str, Any]] = [
    {
        "name": "spaces/ENG",
        "displayName": "Engineering",
        "spaceUri": "https://chat.google.com/room/ENG",
        "lastActiveTime": "2026-10-02T15:00:00Z",
    },
    {
        "name": "spaces/RANDOM",
        "displayName": "Random",
        "spaceUri": "https://chat.google.com/room/RANDOM",
        "lastActiveTime": "2026-09-01T00:00:00Z",
    },
]

# Dave is suspended and the admin is only invited, so Bob reads Engineering.
_MEMBERS: dict[str, list[dict[str, Any]]] = {
    "spaces/ENG": [
        {"state": "JOINED", "member": {"name": "users/4"}},
        {"state": "INVITED", "member": {"name": "users/1"}},
        {"state": "JOINED", "member": {"name": "users/2"}},
        {"state": "JOINED", "member": {"name": "users/5"}},
    ],
    "spaces/RANDOM": [{"state": "JOINED", "member": {"name": "users/1"}}],
}


def _message(
    message_id: str,
    created: str,
    thread: str,
    *,
    sender: str = "users/2",
    sender_name: str | None = "Bob Builder",
    text: str | None = None,
    reply: bool = False,
    attachment: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "name": f"spaces/ENG/messages/{message_id}",
        "createTime": created,
        "thread": {"name": f"spaces/ENG/threads/{thread}"},
        "threadReply": reply,
        "sender": {"name": sender, "type": "HUMAN"},
    }
    if sender_name:
        message["sender"]["displayName"] = sender_name
    if text:
        message["text"] = text
    if attachment:
        message["attachment"] = [{"contentName": attachment}]
    return message


_MESSAGES: dict[str, list[dict[str, Any]]] = {
    "spaces/ENG": [
        _message("m1", "2026-10-01T09:00:00Z", "t1", text="Ship the release?"),
        _message(
            "m2",
            "2026-10-01T09:05:00.123456Z",
            "t1",
            sender="users/3",
            sender_name=None,
            text="Yes, ship it",
            reply=True,
        ),
        # A card-only bot message has no text and is skipped.
        _message("m3", "2026-10-01T10:00:00Z", "t3", sender="users/app"),
        _message("m4", "2026-10-02T08:00:00Z", "t2", attachment="plan.pdf"),
        _message("m5", "2026-10-02T15:00:00Z", "t1", text="Shipped", reply=True),
    ],
    "spaces/RANDOM": [],
}


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"refused")


class _Request:
    def __init__(self, response: dict[str, Any] | HttpError) -> None:
        self._response = response

    def execute(self) -> dict[str, Any]:
        if isinstance(self._response, HttpError):
            raise self._response
        return self._response


def _times(query: str, field: str, operator: str) -> list[datetime]:
    pattern: str = rf'{field} {operator} "([^"]+)"'
    return [datetime.fromisoformat(value) for value in re.findall(pattern, query)]


class _FakeChat:
    """The Chat API as one user sees it: the admin searches spaces and
    members, a member reads messages."""

    def __init__(self, world: "_World", user_email: str) -> None:
        self._world = world
        self._user_email = user_email

    def spaces(self) -> "_FakeChat":
        return self

    def members(self) -> "_FakeChat":
        return self

    def messages(self) -> "_FakeChat":
        return self

    def search(self, query: str, useAdminAccess: bool, **_: Any) -> _Request:
        assert useAdminAccess and self._user_email == _ADMIN
        active_after: list[datetime] = _times(query, "lastActiveTime", ">")
        return _Request(
            {
                "results": [
                    {"space": space}
                    for space in _SPACES
                    if not active_after
                    or datetime.fromisoformat(space["lastActiveTime"]) > active_after[0]
                ]
            }
        )

    def list(self, parent: str, filter: str | None = None, **kwargs: Any) -> _Request:
        if kwargs.get("useAdminAccess"):
            assert filter == 'member.type = "HUMAN"'
            return _Request({"memberships": _MEMBERS[parent]})
        self._world.readers.append(self._user_email)
        self._world.message_filters.append(filter)
        if self._user_email in self._world.refused_readers:
            return _Request(_http_error(403))
        after: list[datetime] = _times(filter or "", "createTime", ">")
        before: list[datetime] = _times(filter or "", "createTime", "<")
        return _Request(
            {
                "messages": [
                    message
                    for message in _MESSAGES[parent]
                    if (created := datetime.fromisoformat(message["createTime"]))
                    and (not after or created > after[0])
                    and (not before or created < before[0])
                ]
            }
        )


class _FakeDirectory:
    def __init__(self, world: "_World") -> None:
        self._world = world

    def users(self) -> "_FakeDirectory":
        return self

    def get(self, userKey: str, **_: Any) -> _Request:
        if self._world.directory_error is not None:
            return _Request(self._world.directory_error)
        user: dict[str, Any] | None = _USERS.get(userKey) or next(
            (u for u in _USERS.values() if u["primaryEmail"] == userKey), None
        )
        return _Request(user if user is not None else _http_error(404))


class _World:
    def __init__(self) -> None:
        self.readers: list[str] = []
        self.message_filters: list[str | None] = []
        self.refused_readers: set[str] = set()
        self.directory_error: HttpError | None = None

    def service(
        self, service: GoogleService, creds: Any, user_email: str | None = None
    ) -> Any:
        assert user_email is not None and creds is not None
        if service == GoogleService.ADMIN:
            return _FakeDirectory(self)
        return _FakeChat(self, user_email)


@pytest.fixture
def world() -> Iterator[_World]:
    fake_world = _World()
    with patch.object(
        google_chat_module, "get_google_service", side_effect=fake_world.service
    ):
        yield fake_world


def _connector(spaces: list[str] | None = None) -> GoogleChatConnector:
    connector = GoogleChatConnector(spaces=spaces)
    with patch.object(
        google_chat_module,
        "get_google_creds",
        return_value=(MagicMock(spec=ServiceAccountCredentials), None),
    ):
        connector.load_credentials(
            {"google_service_account_key": "{}", "google_primary_admin": _ADMIN}
        )
    return connector


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _items(
    connector: GoogleChatConnector, start: float, end: float
) -> list[Document | ConnectorFailure]:
    return [
        item
        for output in load_everything_from_checkpoint_connector(connector, start, end)
        for item in output.items
    ]


def test_full_index_makes_one_document_per_space_day(world: _World) -> None:
    items = _items(_connector(), 0, _ts("2026-10-30T00:00:00Z"))

    assert [item.id for item in items if isinstance(item, Document)] == [
        "google_chat:spaces/ENG:2026-10-01",
        "google_chat:spaces/ENG:2026-10-02",
    ]
    day_one, day_two = items
    assert isinstance(day_one, Document) and isinstance(day_two, Document)
    assert day_one.semantic_identifier == "Engineering - 2026-10-01"
    assert day_one.sections[0].link == "https://chat.google.com/room/ENG"
    # A former member is named from the directory.
    assert day_one.sections[0].text == (
        "Bob Builder: Ship the release?\n    Carol Coder: Yes, ship it"
    )
    assert [owner.email for owner in day_one.primary_owners or []] == [
        "bob@acme.com",
        "carol@acme.com",
    ]
    # Threads keep the order of their first message on the day.
    assert day_two.sections[0].text == (
        "Bob Builder: [Attachment: plan.pdf]\n\n    Bob Builder: Shipped"
    )
    assert day_two.doc_updated_at == datetime(2026, 10, 2, 15, tzinfo=timezone.utc)
    assert day_two.parent_hierarchy_raw_node_id == "spaces/ENG"
    # The suspended member is passed over and the empty space is still read.
    assert world.readers == ["bob@acme.com", _ADMIN]


def test_poll_rebuilds_the_whole_day_of_each_new_message(world: _World) -> None:
    items = _items(
        _connector(), _ts("2026-10-02T12:00:00Z"), _ts("2026-10-03T00:00:00Z")
    )

    assert len(items) == 1
    assert isinstance(items[0], Document)
    assert items[0].id == "google_chat:spaces/ENG:2026-10-02"
    assert "plan.pdf" in (items[0].sections[0].text or "")
    # Random had no message after the window start, so it is not read.
    assert world.message_filters == [
        'createTime > "2026-10-01T23:59:59Z" AND createTime < "2026-10-03T00:00:00Z"'
    ]


@pytest.mark.usefixtures("world")
def test_space_filter_matches_display_name_or_id() -> None:
    by_name = _items(_connector(["engineering"]), 0, _ts("2026-10-30T00:00:00Z"))
    by_id = _items(_connector(["RANDOM"]), 0, _ts("2026-10-30T00:00:00Z"))

    assert len(by_name) == 2
    assert by_id == []


def test_next_member_reads_when_google_refuses_one(world: _World) -> None:
    world.refused_readers = {"bob@acme.com"}

    items = _items(_connector(["Engineering"]), 0, _ts("2026-10-30T00:00:00Z"))

    assert len(items) == 2
    assert world.readers == ["bob@acme.com", "erin@acme.com"]


def test_space_no_member_can_read_is_a_failure(world: _World) -> None:
    world.refused_readers = {"bob@acme.com", "erin@acme.com"}

    items = _items(_connector(["Engineering"]), 0, _ts("2026-10-30T00:00:00Z"))

    assert len(items) == 1
    assert isinstance(items[0], ConnectorFailure)
    assert items[0].failed_entity is not None
    assert items[0].failed_entity.entity_id == "spaces/ENG"


@pytest.mark.usefixtures("world")
def test_slim_listing_matches_indexed_documents() -> None:
    connector = _connector()
    indexed: set[str] = {
        item.id
        for item in _items(connector, 0, _ts("2026-10-30T00:00:00Z"))
        if isinstance(item, Document)
    }

    slim: set[str] = {
        doc.id
        for batch in connector.retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    }

    assert slim == indexed


def test_slim_listing_raises_when_no_member_can_read(world: _World) -> None:
    world.refused_readers = {"bob@acme.com", "erin@acme.com"}

    with pytest.raises(google_chat_module.SpaceUnreadableError):
        list(_connector().retrieve_all_slim_docs())


def test_refused_directory_read_raises(world: _World) -> None:
    world.directory_error = _http_error(403)

    with pytest.raises(HttpError):
        list(_connector().retrieve_all_slim_docs())


def test_key_google_refuses_is_an_invalid_credential() -> None:
    # google-auth raises with Google's message and the raw token response.
    refused = RefreshError(
        "invalid_grant: Invalid grant: account not found",
        {"error": "invalid_grant", "error_description": "account not found"},
    )

    with (
        patch.object(google_chat_module, "get_google_creds", side_effect=refused),
        pytest.raises(
            CredentialInvalidError,
            match=r"^Google rejected the service account key: "
            r"invalid_grant: Invalid grant: account not found$",
        ),
    ):
        GoogleChatConnector().load_credentials(
            {"google_service_account_key": "{}", "google_primary_admin": _ADMIN}
        )


def test_oauth_credential_is_rejected() -> None:
    with pytest.raises(CredentialInvalidError):
        GoogleChatConnector().load_credentials(
            {"google_tokens": "{}", "google_primary_admin": _ADMIN}
        )
