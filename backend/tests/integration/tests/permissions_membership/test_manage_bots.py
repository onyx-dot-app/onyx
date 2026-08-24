"""Integration tests for MANAGE_BOTS permission gate.

MANAGE_BOTS protects the Slack-bot admin endpoints in
``backend/onyx/server/manage/slack_bot.py`` (router prefix ``/manage``)
and the Discord-bot admin endpoints in
``backend/onyx/server/manage/discord_bot/api.py`` (router prefix
``/manage/admin/discord-bot``).

Bogus ids are fine: the gate runs before the handler, and none of these routes
call Slack or Discord.

The Discord ``/config`` and ``/service-api-key`` routes are absent on purpose —
``_check_bot_config_api_access`` raises INSUFFICIENT_PERMISSIONS when the bot is
env- or Cloud-managed, which the matrix would read as a gate denial.
"""

import os
from typing import Any

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.test_models import DATestAPIKey, DATestUser
from tests.integration.tests.permissions._access_matrix import (
    USER_KINDS,
    Endpoint,
    assert_response,
    call_endpoint,
    resolve_credentials,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Custom group permission assignment is enterprise only",
)

PERMISSION = Permission.MANAGE_BOTS.value

_SLACK_CHANNEL_BODY: dict[str, Any] = {
    "slack_bot_id": 999999,
    "channel_name": "perm-test-channel",
    "persona_id": None,
    "document_sets": [],
    "enable_auto_filters": False,
    "respond_tag_only": False,
    "respond_to_bots": False,
    "is_ephemeral": False,
    "respond_member_group_list": [],
    "follow_up_tags": [],
    "show_continue_in_web_ui": False,
}

# Discord's update models have no `is_active`; both PATCH handlers 404 cleanly on a
# missing id, so a complete body reaches them the way the bogus ids elsewhere do.
_DISCORD_GUILD_BODY: dict[str, Any] = {
    "enabled": False,
    "default_persona_id": None,
}

_DISCORD_CHANNEL_BODY: dict[str, Any] = {
    "require_bot_invocation": False,
    "persona_override_id": None,
    "enabled": False,
    "thread_only_mode": False,
}

_DISCORD_GUILDS_PATH = "/manage/admin/discord-bot/guilds"

# Both bot surfaces, every method — a GET-only list would miss a mutating route
# losing its gate.
ENDPOINTS: list[Endpoint] = [
    # Slack — channel configs
    ("GET", "/manage/admin/slack-app/channel", None),
    ("POST", "/manage/admin/slack-app/channel", _SLACK_CHANNEL_BODY),
    ("PATCH", "/manage/admin/slack-app/channel/999999", _SLACK_CHANNEL_BODY),
    ("DELETE", "/manage/admin/slack-app/channel/999999", None),
    # Slack — bots
    ("GET", "/manage/admin/slack-app/bots", None),
    ("GET", "/manage/admin/slack-app/bots/999999", None),
    ("GET", "/manage/admin/slack-app/bots/999999/config", None),
    ("PATCH", "/manage/admin/slack-app/bots/999999", {"name": "perm-test-bot"}),
    ("DELETE", "/manage/admin/slack-app/bots/999999", None),
    # Discord — guilds and their channels
    ("GET", _DISCORD_GUILDS_PATH, None),
    ("POST", _DISCORD_GUILDS_PATH, None),
    ("GET", "/manage/admin/discord-bot/guilds/999999", None),
    ("PATCH", "/manage/admin/discord-bot/guilds/999999", _DISCORD_GUILD_BODY),
    ("DELETE", "/manage/admin/discord-bot/guilds/999999", None),
    ("GET", "/manage/admin/discord-bot/guilds/999999/channels", None),
    (
        "PATCH",
        "/manage/admin/discord-bot/guilds/999999/channels/999999",
        _DISCORD_CHANNEL_BODY,
    ),
]


@pytest.fixture(scope="module")
def holder_user(permission_holder_user_factory: Any) -> DATestUser:
    return permission_holder_user_factory(PERMISSION)


@pytest.fixture(scope="module")
def holder_service_account(
    permission_holder_service_account_factory: Any,
) -> DATestAPIKey:
    return permission_holder_service_account_factory(PERMISSION)


@pytest.mark.parametrize("user_kind,expected", USER_KINDS)
@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_access_matrix(
    user_kind: str,
    expected: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    request: pytest.FixtureRequest,
    permission_admin_user: DATestUser,  # noqa: ARG001 -- ensures module_reset ran
) -> None:
    headers, cookies = resolve_credentials(user_kind, request)
    resp = call_endpoint(method, path, body, headers, cookies)
    assert_response(resp, method, path, user_kind, expected)

    # the guild POST is the one endpoint here that really creates
    if method == "POST" and path == _DISCORD_GUILDS_PATH and resp.status_code == 200:
        call_endpoint(
            "DELETE",
            f"{_DISCORD_GUILDS_PATH}/{resp.json()['id']}",
            None,
            headers,
            cookies,
        )
