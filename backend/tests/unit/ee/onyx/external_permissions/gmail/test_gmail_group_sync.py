"""The Gmail group sync gives each Collaborative Inbox group the readers its view
setting allows. A group that no longer qualifies or has an unknown setting gets
none, and one that cannot be read fails alone."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.gmail import group_sync
from ee.onyx.external_permissions.gmail.group_sync import gmail_group_sync
from ee.onyx.external_permissions.models import SyncEntityFailure
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.gmail.connector import GmailConnector
from onyx.db.enums import SyncEntityKind

_GROUP = "support@example.com"
_OTHER_GROUP = "legal@example.com"
_THIRD_GROUP = "press@example.com"
_OWNER = "owner@example.com"
_MANAGER = "manager@example.com"
_MEMBER = "member@example.com"
_PARTNER = "partner@other.com"
_NESTED_MEMBER = "nested-member@example.com"
_NESTED_PARTNER = "nested-partner@other.com"
_NON_MEMBER = "non-member@example.com"

_DIRECT_MEMBERS = [
    {"email": "Owner@example.com", "role": "OWNER", "type": "USER"},
    {"email": _MANAGER, "role": "MANAGER", "type": "USER"},
    {"email": _MEMBER, "role": "MEMBER", "type": "USER"},
    {"email": _PARTNER, "role": "MEMBER", "type": "USER"},
    {"email": "tier2@example.com", "role": "MANAGER", "type": "GROUP"},
]
_NESTED_MEMBERS = [
    {"email": _NESTED_MEMBER, "role": "MEMBER", "type": "USER"},
    {"email": _NESTED_PARTNER, "role": "MEMBER", "type": "USER"},
]
_WHOLE_ACCOUNT_MEMBER = {"role": "MEMBER", "type": "CUSTOMER"}
_ACCOUNT_USERS = [_OWNER, _MANAGER, _MEMBER, _NESTED_MEMBER, _NON_MEMBER]


def _http_error(status: int) -> HttpError:
    return HttpError(
        resp=httplib2.Response({"status": status}),
        content=json.dumps({"error": {"code": status, "message": "error"}}).encode(),
    )


def _request(result: dict[str, Any] | HttpError) -> MagicMock:
    request = MagicMock()
    if isinstance(result, HttpError):
        request.execute.side_effect = result
    else:
        request.execute.return_value = result
    return request


def _settings(view: str, collaborative_inbox: str = "true") -> dict[str, Any]:
    return {"enableCollaborativeInbox": collaborative_inbox, "whoCanViewGroup": view}


class _Directory:
    """A fake Workspace: one member list for every group, and the account's
    users. A group in ``unreadable_member_groups`` fails its member listing."""

    def __init__(
        self,
        settings_by_group: dict[str, dict[str, Any] | HttpError],
        direct_members: list[dict[str, Any]] | None = None,
        unreadable_member_groups: tuple[str, ...] = (),
    ) -> None:
        self.settings_by_group = settings_by_group
        self.direct_members = (
            _DIRECT_MEMBERS if direct_members is None else direct_members
        )
        self.unreadable_member_groups = unreadable_member_groups
        self.settings_service = MagicMock()
        self.settings_service.groups.return_value.get.side_effect = (
            lambda groupUniqueId, **_: _request(self.settings_by_group[groupUniqueId])
        )
        self.admin_service = MagicMock()
        self.admin_service.members.return_value.list.side_effect = self._list_members
        self.admin_service.users.return_value.list.side_effect = lambda **_: _request(
            {"users": [{"primaryEmail": email} for email in _ACCOUNT_USERS]}
        )

    def _list_members(
        self, groupKey: str, includeDerivedMembership: bool, **_: Any
    ) -> MagicMock:
        if groupKey in self.unreadable_member_groups:
            return _request(_http_error(403))
        members = [*self.direct_members]
        if includeDerivedMembership:
            members += _NESTED_MEMBERS
        return _request({"members": members})

    @property
    def user_listing_count(self) -> int:
        return self.admin_service.users.return_value.list.call_count

    def sync(
        self, has_settings_scope: bool = True
    ) -> list[ExternalUserGroup | SyncEntityFailure]:
        cc_pair = MagicMock()
        cc_pair.connector.source = DocumentSource.GMAIL
        cc_pair.connector.connector_specific_config = {
            "collaborative_inbox_groups": list(self.settings_by_group)
        }

        def load_credentials(connector: GmailConnector, _: dict[str, Any]) -> None:
            connector._creds = MagicMock()
            connector._primary_admin_email = "admin@example.com"

        with (
            patch.object(group_sync, "credential_json", return_value={}),
            patch.object(
                GmailConnector, "load_credentials", autospec=True
            ) as self.load_credentials,
            patch.object(
                group_sync,
                "build_groups_settings_service",
                return_value=self.settings_service if has_settings_scope else None,
            ),
            patch.object(
                group_sync, "get_google_service", return_value=self.admin_service
            ),
        ):
            self.load_credentials.side_effect = load_credentials
            return list(gmail_group_sync("tenant", cc_pair))


@pytest.mark.parametrize(
    ("view", "reader_emails"),
    [
        ("ALL_OWNERS_CAN_VIEW", [_OWNER]),
        ("ALL_MANAGERS_CAN_VIEW", [_MANAGER, _OWNER]),
        # A nested member from outside the account does not get the group's
        # mail from Google, so the partner in the nested group is left out.
        ("ALL_MEMBERS_CAN_VIEW", [_MANAGER, _MEMBER, _NESTED_MEMBER, _OWNER, _PARTNER]),
        ("ALL_IN_DOMAIN_CAN_VIEW", sorted(_ACCOUNT_USERS)),
        ("ANYONE_CAN_VIEW", sorted(_ACCOUNT_USERS)),
        ("A_VALUE_GOOGLE_ADDS_LATER", []),
    ],
)
def test_group_readers_follow_the_view_setting(
    view: str, reader_emails: list[str]
) -> None:
    groups = _Directory({_GROUP: _settings(view)}).sync()

    assert groups == [ExternalUserGroup(id=_GROUP, user_emails=reader_emails)]


def test_role_listings_ask_google_for_the_roles() -> None:
    directory = _Directory({_GROUP: _settings("ALL_MANAGERS_CAN_VIEW")})

    directory.sync()

    list_kwargs = directory.admin_service.members.return_value.list.call_args.kwargs
    assert list_kwargs["roles"] == "MANAGER,OWNER"
    assert list_kwargs["includeDerivedMembership"] is False


def test_a_whole_account_member_makes_every_account_user_a_reader() -> None:
    directory = _Directory(
        {_GROUP: _settings("ALL_MEMBERS_CAN_VIEW")},
        direct_members=[*_DIRECT_MEMBERS, _WHOLE_ACCOUNT_MEMBER],
    )

    groups = directory.sync()

    assert groups == [
        ExternalUserGroup(id=_GROUP, user_emails=sorted({*_ACCOUNT_USERS, _PARTNER}))
    ]


def test_the_account_users_are_listed_once_for_all_groups() -> None:
    directory = _Directory(
        {
            _GROUP: _settings("ALL_IN_DOMAIN_CAN_VIEW"),
            _OTHER_GROUP: _settings("ANYONE_CAN_VIEW"),
        }
    )

    groups = directory.sync()

    assert [group.id for group in groups] == [_OTHER_GROUP, _GROUP]
    assert directory.user_listing_count == 1


@pytest.mark.parametrize(
    "settings",
    [_settings("ALL_MEMBERS_CAN_VIEW", collaborative_inbox="false"), _http_error(404)],
    ids=["Collaborative Inbox turned off", "group deleted"],
)
def test_a_group_that_stopped_qualifying_has_no_readers(
    settings: dict[str, Any] | HttpError,
) -> None:
    groups = _Directory({_GROUP: settings}).sync()

    assert groups == [ExternalUserGroup(id=_GROUP, user_emails=[])]


def _assert_failed_alone(groups: list[ExternalUserGroup | SyncEntityFailure]) -> None:
    # The connector config keeps its groups sorted.
    assert groups[:2] == [
        ExternalUserGroup(id=_OTHER_GROUP, user_emails=[_OWNER]),
        ExternalUserGroup(id=_THIRD_GROUP, user_emails=[_OWNER]),
    ]
    assert len(groups) == 3
    failure = groups[2]
    assert isinstance(failure, SyncEntityFailure)
    assert (failure.kind, failure.id) == (SyncEntityKind.GROUP, _GROUP)


def test_a_group_whose_settings_cannot_be_read_fails_alone() -> None:
    groups = _Directory(
        {
            _GROUP: _http_error(403),
            _OTHER_GROUP: _settings("ALL_OWNERS_CAN_VIEW"),
            _THIRD_GROUP: _settings("ALL_OWNERS_CAN_VIEW"),
        }
    ).sync()

    _assert_failed_alone(groups)


def test_a_group_whose_members_cannot_be_read_fails_alone() -> None:
    """An unreadable member list is a failure, never a group with no readers."""
    groups = _Directory(
        {
            _GROUP: _settings("ALL_OWNERS_CAN_VIEW"),
            _OTHER_GROUP: _settings("ALL_OWNERS_CAN_VIEW"),
            _THIRD_GROUP: _settings("ALL_OWNERS_CAN_VIEW"),
        },
        unreadable_member_groups=(_GROUP,),
    ).sync()

    _assert_failed_alone(groups)


def test_sync_fails_when_most_groups_cannot_be_read() -> None:
    directory = _Directory({_GROUP: _http_error(403), _OTHER_GROUP: _http_error(403)})

    with pytest.raises(RuntimeError, match="Too many groups failed"):
        directory.sync()


def test_an_account_past_the_user_limit_fails_the_group_that_needs_it() -> None:
    """A cut-off user list must never be taken as the whole account."""
    directory = _Directory(
        {
            _GROUP: _settings("ALL_IN_DOMAIN_CAN_VIEW"),
            _OTHER_GROUP: _settings("ALL_OWNERS_CAN_VIEW"),
            _THIRD_GROUP: _settings("ALL_OWNERS_CAN_VIEW"),
        }
    )

    with patch.object(group_sync, "_MAX_ACCOUNT_USERS", 2):
        groups = directory.sync()

    _assert_failed_alone(groups)


def test_sync_stops_at_its_deadline() -> None:
    directory = _Directory({_GROUP: _settings("ALL_IN_DOMAIN_CAN_VIEW")})

    with (
        patch.object(group_sync, "PERMISSION_SYNC_TIMEOUT", -1),
        pytest.raises(TimeoutError, match="Gmail group sync exceeded"),
    ):
        directory.sync()


def test_sync_fails_without_the_settings_scope() -> None:
    directory = _Directory({_GROUP: _settings("ALL_MEMBERS_CAN_VIEW")})

    with pytest.raises(InsufficientPermissionsError, match="apps.groups.settings"):
        directory.sync(has_settings_scope=False)


def test_sync_makes_no_call_without_listed_groups() -> None:
    directory = _Directory({})

    assert directory.sync() == []
    directory.load_credentials.assert_not_called()
