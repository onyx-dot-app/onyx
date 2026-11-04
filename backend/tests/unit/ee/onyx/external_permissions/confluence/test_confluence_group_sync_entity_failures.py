"""Confluence group sync skips a user whose groups it cannot read whole, never
with the groups read before the error, reports the user as a
SyncEntityFailure, and fails the sync once more than half of the users fail."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.confluence import group_sync
from ee.onyx.external_permissions.confluence.constants import ALL_CONF_EMAILS_GROUP_NAME
from ee.onyx.external_permissions.models import SyncEntityFailure
from onyx.connectors.confluence.models import ConfluenceUser
from onyx.db.enums import SyncEntityKind


def _user(user_id: str) -> ConfluenceUser:
    return ConfluenceUser(
        user_id=user_id,
        username=None,
        display_name=user_id,
        email=f"{user_id}@a.com",
        type="known",
    )


def _run_confluence_group_sync(
    user_groups: dict[str, list[str] | Exception],
) -> list[ExternalUserGroup | SyncEntityFailure]:
    def _list_user_groups(user_id: str) -> Iterator[dict[str, Any]]:
        groups = user_groups[user_id]
        if isinstance(groups, Exception):
            # The first page reads before the error, so a partial list exists.
            yield {"name": "engineering"}
            raise groups
        yield from ({"name": name} for name in groups)

    source_operations = MagicMock()
    source_operations.list_users.return_value = [_user(uid) for uid in user_groups]
    source_operations.list_user_groups.side_effect = _list_user_groups
    cc_pair = MagicMock()
    cc_pair.connector.connector_specific_config = {"is_cloud": True}
    with (
        patch.object(group_sync, "OnyxDBCredentialsProvider"),
        patch.object(
            group_sync,
            "build_probed_confluence_gateway",
            return_value=source_operations,
        ),
    ):
        return list(group_sync.confluence_group_sync("tenant", cc_pair))


def test_failing_user_is_skipped_whole_and_reported() -> None:
    items = _run_confluence_group_sync(
        {
            "alice": ["engineering"],
            "bob": RuntimeError("429 retries exhausted"),
            "carol": ["engineering", "sales"],
        }
    )

    failures = [item for item in items if isinstance(item, SyncEntityFailure)]
    assert len(failures) == 1
    assert failures[0].kind == SyncEntityKind.USER
    assert failures[0].id == "bob"
    assert failures[0].name == "bob@a.com"
    assert failures[0].message == "429 retries exhausted"

    groups = {
        item.id: set(item.user_emails)
        for item in items
        if isinstance(item, ExternalUserGroup)
    }
    assert groups == {
        "engineering": {"alice@a.com", "carol@a.com"},
        "sales": {"carol@a.com"},
        ALL_CONF_EMAILS_GROUP_NAME: {"alice@a.com", "carol@a.com"},
    }


def test_too_many_failed_users_fail_the_sync() -> None:
    with pytest.raises(RuntimeError, match="Too many failed user group fetches"):
        _run_confluence_group_sync(
            {
                "alice": RuntimeError("down"),
                "bob": RuntimeError("down"),
                "carol": ["engineering"],
            }
        )


def test_onyx_users_variant_skips_and_reports_a_failing_user() -> None:
    def _list_user_groups(user_id: str) -> Iterator[dict[str, Any]]:
        yield {"name": "engineering"}
        if user_id == "key-bob":
            raise RuntimeError("500")

    source_operations = MagicMock()
    source_operations.get_user_by_username.side_effect = lambda username: {
        "userKey": f"key-{username}"
    }
    source_operations.list_user_groups.side_effect = _list_user_groups
    onyx_users = [MagicMock(email="alice@a.com"), MagicMock(email="bob@a.com")]
    with (
        patch.object(group_sync, "get_session_with_current_tenant"),
        patch.object(group_sync, "get_all_users", return_value=onyx_users),
    ):
        group_member_emails, failures = (
            group_sync._build_group_member_email_map_from_onyx_users(source_operations)
        )

    assert group_member_emails == {"engineering": {"alice@a.com"}}
    assert [(f.kind, f.id, f.message) for f in failures] == [
        (SyncEntityKind.USER, "bob@a.com", "500")
    ]


def test_failed_server_email_lookup_is_reported() -> None:
    """The Server email lookup returns None on an error, so a user it cannot
    resolve is reported, counted toward the cap, and in no group. An app user
    without an email is skipped unreported."""
    users = [
        _user("alice"),
        ConfluenceUser(
            user_id="key-bob",
            username="bob",
            display_name="Bob",
            email=None,
            type="known",
        ),
        ConfluenceUser(
            user_id="key-bot",
            username="bot",
            display_name="Bot",
            email=None,
            type="app",
        ),
        _user("carol"),
    ]
    source_operations = MagicMock()
    source_operations.list_users.return_value = users
    source_operations.get_listed_user_email.return_value = None
    source_operations.list_user_groups.return_value = [{"name": "engineering"}]

    group_member_emails, failures = group_sync._build_group_member_email_map(
        source_operations, cc_pair_id=1
    )

    assert group_member_emails == {"engineering": {"alice@a.com", "carol@a.com"}}
    assert [(f.kind, f.id, f.name) for f in failures] == [
        (SyncEntityKind.USER, "key-bob", "bob")
    ]

    source_operations.list_users.return_value = [users[1], users[1], _user("carol")]
    with pytest.raises(RuntimeError, match="Too many failed user group fetches"):
        group_sync._build_group_member_email_map(source_operations, cc_pair_id=1)
