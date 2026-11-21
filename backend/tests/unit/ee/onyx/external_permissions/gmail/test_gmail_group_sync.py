"""The Gmail group sync gives each Collaborative Inbox group the readers that
the group's own view setting allows, and nobody when it cannot tell."""

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
_NESTED_MEMBER = "nested-member@example.com"
_NON_MEMBER = "non-member@example.com"

_DIRECT_MEMBERS = [
    {"email": "Owner@example.com", "role": "OWNER", "type": "USER"},
    {"email": _MANAGER, "role": "MANAGER", "type": "USER"},
    {"email": _MEMBER, "role": "MEMBER", "type": "USER"},
    {"email": "tier2@example.com", "role": "MANAGER", "type": "GROUP"},
]
_DERIVED_MEMBERS = [
    *_DIRECT_MEMBERS,
    {"email": _NESTED_MEMBER, "role": "MEMBER", "type": "USER"},
]
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


def _sync(
    settings_by_group: dict[str, dict[str, Any] | HttpError],
    has_settings_scope: bool = True,
) -> tuple[list[ExternalUserGroup | SyncEntityFailure], MagicMock]:
    """Runs the group sync for the groups in ``settings_by_group`` against a
    fake directory. Also returns the mock that loads the credential."""
    settings_service = MagicMock()
    settings_service.groups.return_value.get.side_effect = lambda groupUniqueId, **_: (
        _request(settings_by_group[groupUniqueId])
    )
    admin_service = MagicMock()
    admin_service.members.return_value.list.side_effect = (
        lambda includeDerivedMembership=False, **_: _request(
            {
                "members": _DERIVED_MEMBERS
                if includeDerivedMembership
                else _DIRECT_MEMBERS
            }
        )
    )
    admin_service.users.return_value.list.side_effect = lambda **_: _request(
        {"users": [{"primaryEmail": email} for email in _ACCOUNT_USERS]}
    )

    cc_pair = MagicMock()
    cc_pair.connector.source = DocumentSource.GMAIL
    cc_pair.connector.connector_specific_config = {
        "collaborative_inbox_groups": list(settings_by_group)
    }

    def load_credentials(connector: GmailConnector, _: dict[str, Any]) -> None:
        connector._creds = MagicMock()
        connector._primary_admin_email = "admin@example.com"

    with (
        patch.object(group_sync, "credential_json", return_value={}),
        patch.object(
            GmailConnector, "load_credentials", autospec=True
        ) as load_credentials_mock,
        patch.object(
            group_sync,
            "build_groups_settings_service",
            return_value=settings_service if has_settings_scope else None,
        ),
        patch.object(group_sync, "get_google_service", return_value=admin_service),
    ):
        load_credentials_mock.side_effect = load_credentials
        return list(gmail_group_sync("tenant", cc_pair)), load_credentials_mock


@pytest.mark.parametrize(
    ("view", "reader_emails"),
    [
        ("ALL_OWNERS_CAN_VIEW", [_OWNER]),
        ("ALL_MANAGERS_CAN_VIEW", [_MANAGER, _OWNER]),
        ("ALL_MEMBERS_CAN_VIEW", [_MANAGER, _MEMBER, _NESTED_MEMBER, _OWNER]),
        ("ALL_IN_DOMAIN_CAN_VIEW", sorted(_ACCOUNT_USERS)),
        # Open to the web in Google, and still only the Workspace account here.
        ("ANYONE_CAN_VIEW", sorted(_ACCOUNT_USERS)),
        ("A_VALUE_GOOGLE_ADDS_LATER", []),
    ],
)
def test_group_readers_follow_the_view_setting(
    view: str, reader_emails: list[str]
) -> None:
    groups, _ = _sync({_GROUP: _settings(view)})

    assert groups == [ExternalUserGroup(id=_GROUP, user_emails=reader_emails)]


@pytest.mark.parametrize(
    "settings",
    [_settings("ALL_MEMBERS_CAN_VIEW", collaborative_inbox="false"), _http_error(404)],
    ids=["Collaborative Inbox turned off", "group deleted"],
)
def test_a_group_that_stopped_qualifying_has_no_readers(
    settings: dict[str, Any] | HttpError,
) -> None:
    groups, _ = _sync({_GROUP: settings})

    assert groups == [ExternalUserGroup(id=_GROUP, user_emails=[])]


def test_a_group_that_cannot_be_read_fails_alone() -> None:
    groups, _ = _sync(
        {
            _GROUP: _http_error(403),
            _OTHER_GROUP: _settings("ALL_OWNERS_CAN_VIEW"),
            _THIRD_GROUP: _settings("ALL_OWNERS_CAN_VIEW"),
        }
    )

    # The connector config keeps its groups sorted.
    assert groups[:2] == [
        ExternalUserGroup(id=_OTHER_GROUP, user_emails=[_OWNER]),
        ExternalUserGroup(id=_THIRD_GROUP, user_emails=[_OWNER]),
    ]
    failure = groups[2]
    assert isinstance(failure, SyncEntityFailure)
    assert (failure.kind, failure.id) == (SyncEntityKind.GROUP, _GROUP)


def test_sync_fails_when_most_groups_cannot_be_read() -> None:
    with pytest.raises(RuntimeError, match="Too many groups failed"):
        _sync({_GROUP: _http_error(403), _OTHER_GROUP: _http_error(403)})


def test_sync_fails_without_the_settings_scope() -> None:
    """A sync that returned no groups would hide every group document with no
    error for the admin to see."""
    with pytest.raises(InsufficientPermissionsError, match="apps.groups.settings"):
        _sync({_GROUP: _settings("ALL_MEMBERS_CAN_VIEW")}, has_settings_scope=False)


def test_sync_makes_no_call_without_listed_groups() -> None:
    groups, load_credentials_mock = _sync({})

    assert groups == []
    load_credentials_mock.assert_not_called()
