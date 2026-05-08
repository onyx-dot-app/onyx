"""Dispatcher-level tests for Confluence space permission sync.

The companion file `backend/tests/unit/onyx/connectors/confluence/test_onyx_confluence.py`
covers the OnyxConfluence client methods (REST 404/500 handling, version
probe, userKey-email cache). Tests here cover the EE-side dispatcher in
`ee/onyx/external_permissions/confluence/space_access.py` -- which path
gets picked, how the REST response shape is translated into ExternalAccess,
and how the anonymous endpoint plays into is_public.
"""

from collections.abc import Generator
from typing import Any
from unittest import mock

import pytest

from ee.onyx.external_permissions.confluence import space_access
from ee.onyx.external_permissions.confluence.constants import ALL_CONF_EMAILS_GROUP_NAME
from onyx.connectors.confluence.onyx_confluence import (
    ConfluenceRestSpacePermissionsNotAvailableError,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _read_permission_for_group(group_name: str, space_key: str = "ENG") -> dict:
    return {
        "operation": {"targetType": "space", "operationKey": "read"},
        "subject": {"type": "group", "name": group_name},
        "spaceKey": space_key,
        "spaceId": 131083,
    }


def _read_permission_for_user(user_key: str, space_key: str = "ENG") -> dict:
    return {
        "operation": {"targetType": "space", "operationKey": "read"},
        "subject": {"type": "user", "userKey": user_key},
        "spaceKey": space_key,
        "spaceId": 131083,
    }


def _anonymous_read_permission() -> dict:
    return {"operation": {"targetType": "space", "operationKey": "read"}}


def _make_client(
    *,
    supports_rest: bool,
    rest_permissions: list[dict[str, Any]] | Exception | None = None,
    anonymous_permissions: list[dict[str, Any]] | None = None,
    jsonrpc_permissions: list[dict[str, Any]] | None = None,
) -> mock.Mock:
    client = mock.Mock()
    client.supports_rest_space_permissions.return_value = supports_rest

    if isinstance(rest_permissions, Exception):
        client.get_all_space_permissions_server_rest.side_effect = rest_permissions
    else:
        client.get_all_space_permissions_server_rest.return_value = (
            rest_permissions or []
        )

    client.get_anonymous_space_permissions_server_rest.return_value = (
        anonymous_permissions or []
    )
    client.get_all_space_permissions_server.return_value = jsonrpc_permissions or []
    return client


@pytest.fixture
def patched_userkey_resolver() -> Generator[dict[str, str | None], None, None]:
    """Make get_user_email_from_userkey__server return whatever the test
    sets in the returned dict, with no real network involvement.
    """
    fake_db: dict[str, str | None] = {}

    def fake_resolver(_client: object, user_key: str) -> str | None:
        return fake_db.get(user_key)

    with mock.patch.object(
        space_access,
        "get_user_email_from_userkey__server",
        side_effect=fake_resolver,
    ):
        yield fake_db


# ---------------------------------------------------------------------------
# Dispatcher: REST vs JSON-RPC
# ---------------------------------------------------------------------------


def test_dispatcher_uses_rest_for_dc_91_plus(
    patched_userkey_resolver: dict[str, str | None],
) -> None:
    """DC 9.1+ should use the REST API, never touching the legacy JSON-RPC
    method. This is the actual production fix for cc_pair=44 / cc_pair=50.
    """
    patched_userkey_resolver["userkey-alice"] = "alice@example.com"
    client = _make_client(
        supports_rest=True,
        rest_permissions=[
            _read_permission_for_group("confluence-users"),
            _read_permission_for_user("userkey-alice"),
        ],
    )

    access = space_access._get_server_space_permissions(
        confluence_client=client, space_key="ENG"
    )

    assert access.is_public is False
    assert access.external_user_emails == {"alice@example.com"}
    assert access.external_user_group_ids == {"confluence-users"}
    client.get_all_space_permissions_server_rest.assert_called_once_with(
        space_key="ENG"
    )
    client.get_all_space_permissions_server.assert_not_called()


def test_dispatcher_falls_back_to_jsonrpc_for_pre_91() -> None:
    """DC < 9.1 has no REST endpoint; the dispatcher must fall back to the
    legacy JSON-RPC path (and produce identical-shape ExternalAccess).
    """
    client = _make_client(
        supports_rest=False,
        jsonrpc_permissions=[
            {
                "type": "VIEWSPACE",
                "spacePermissions": [
                    {"groupName": "confluence-users", "userName": None},
                ],
            }
        ],
    )

    access = space_access._get_server_space_permissions(
        confluence_client=client, space_key="ENG"
    )

    assert access.external_user_group_ids == {"confluence-users"}
    client.get_all_space_permissions_server.assert_called_once_with(space_key="ENG")
    client.get_all_space_permissions_server_rest.assert_not_called()


def test_dispatcher_falls_back_to_jsonrpc_when_rest_signals_unavailable() -> None:
    """If serverInfo lies (or a custom build doesn't have the REST plugin),
    the REST call raises the typed unavailability signal and the dispatcher
    must fall back rather than blow up.
    """
    client = _make_client(
        supports_rest=True,
        rest_permissions=ConfluenceRestSpacePermissionsNotAvailableError(
            "404 from upstream"
        ),
        jsonrpc_permissions=[
            {
                "type": "VIEWSPACE",
                "spacePermissions": [{"groupName": "fallback-group", "userName": None}],
            }
        ],
    )

    access = space_access._get_server_space_permissions(
        confluence_client=client, space_key="ENG"
    )

    assert access.external_user_group_ids == {"fallback-group"}
    client.get_all_space_permissions_server_rest.assert_called_once()
    client.get_all_space_permissions_server.assert_called_once_with(space_key="ENG")


# ---------------------------------------------------------------------------
# REST response shape: anonymous endpoint
# ---------------------------------------------------------------------------


def test_rest_anonymous_endpoint_marks_public_when_env_var_set() -> None:
    """When the anonymous endpoint reports a 'read' grant AND
    CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC is set, the space surfaces as
    is_public=True. (No surrogate group is added.)

    Doesn't need patched_userkey_resolver because rest_permissions is
    empty -- there are no userKeys to resolve.
    """
    client = _make_client(
        supports_rest=True,
        rest_permissions=[],
        anonymous_permissions=[_anonymous_read_permission()],
    )

    with mock.patch.object(space_access, "CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC", True):
        access = space_access._get_server_space_permissions(
            confluence_client=client, space_key="ENG"
        )

    assert access.is_public is True
    assert access.external_user_emails == set()
    assert access.external_user_group_ids == set()


def test_rest_anonymous_endpoint_falls_back_to_all_users_group_when_env_unset() -> None:
    """Without the env var, the legacy behavior is to add the
    ALL_CONF_EMAILS group so authenticated Confluence users still see the
    space, but the surface isn't marked truly public. Mirror this on the
    REST path.

    Doesn't need patched_userkey_resolver because rest_permissions is
    empty -- there are no userKeys to resolve.
    """
    client = _make_client(
        supports_rest=True,
        rest_permissions=[],
        anonymous_permissions=[_anonymous_read_permission()],
    )

    with mock.patch.object(
        space_access, "CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC", False
    ):
        access = space_access._get_server_space_permissions(
            confluence_client=client, space_key="ENG"
        )

    assert access.is_public is False
    assert access.external_user_group_ids == {ALL_CONF_EMAILS_GROUP_NAME}


def test_rest_anonymous_endpoint_failure_does_not_break_explicit_grants(
    patched_userkey_resolver: dict[str, str | None],
) -> None:
    """If the anonymous endpoint blows up on a single space, that should
    not nuke the explicit user/group grants we already collected from the
    bulk endpoint -- we'd rather lose anonymous detection than lose the
    whole permission set.
    """
    patched_userkey_resolver["userkey-alice"] = "alice@example.com"
    client = _make_client(
        supports_rest=True,
        rest_permissions=[
            _read_permission_for_group("confluence-users"),
            _read_permission_for_user("userkey-alice"),
        ],
    )
    client.get_anonymous_space_permissions_server_rest.side_effect = RuntimeError(
        "anonymous endpoint flaked"
    )

    access = space_access._get_server_space_permissions(
        confluence_client=client, space_key="ENG"
    )

    assert access.is_public is False
    assert access.external_user_emails == {"alice@example.com"}
    assert access.external_user_group_ids == {"confluence-users"}


# ---------------------------------------------------------------------------
# REST response shape: ignored entries
# ---------------------------------------------------------------------------


def test_rest_path_ignores_non_read_and_non_space_permissions(
    patched_userkey_resolver: dict[str, str | None],
) -> None:
    """The REST endpoint returns *all* operations for the space (read,
    update, delete, etc., across multiple targetTypes). Only space-level
    READ entries should contribute to permission sync.
    """
    patched_userkey_resolver["userkey-alice"] = "alice@example.com"
    client = _make_client(
        supports_rest=True,
        rest_permissions=[
            # Should be picked up:
            _read_permission_for_group("confluence-users"),
            _read_permission_for_user("userkey-alice"),
            # Should be ignored: write permission
            {
                "operation": {
                    "targetType": "space",
                    "operationKey": "create",
                },
                "subject": {"type": "group", "name": "writers"},
                "spaceKey": "ENG",
                "spaceId": 131083,
            },
            # Should be ignored: not a space-level operation
            {
                "operation": {"targetType": "page", "operationKey": "read"},
                "subject": {"type": "group", "name": "page-readers"},
                "spaceKey": "ENG",
                "spaceId": 131083,
            },
        ],
    )

    access = space_access._get_server_space_permissions(
        confluence_client=client, space_key="ENG"
    )

    assert access.external_user_emails == {"alice@example.com"}
    assert access.external_user_group_ids == {"confluence-users"}
