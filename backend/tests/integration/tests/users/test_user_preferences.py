"""A user's settings round-trip through the settings endpoints and GET /me.

A new user has no `user_preferences` row: GET /me reports the column
defaults. The first write creates the row; later writes update it.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import UserPreferences
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

DEFAULT_PREFERENCES: dict[str, Any] = {
    "chosen_assistants": None,
    "hidden_assistants": [],
    "visible_assistants": [],
    "default_model": None,
    "pinned_assistants": [],
    "shortcut_enabled": False,
    "auto_scroll": None,
    "temperature_override_enabled": None,
    "temperature_default": None,
    "reasoning_effort_default": None,
    "theme_preference": None,
    "language": None,
    "chat_background": None,
    "default_app_mode": "CHAT",
    "interface_font": "default",
    "response_font": "match",
    "paste_as_tile": False,
    "interrupt_on_send": False,
    "voice_auto_send": False,
    "voice_auto_playback": False,
    "voice_playback_speed": 1.0,
    "assistant_specific_configs": None,
}


def _me(user: DATestUser) -> dict[str, Any]:
    response = client.get(f"{API_SERVER_URL}/me", headers=user.headers)
    response.raise_for_status()
    return response.json()


def _patch(
    user: DATestUser,
    path: str,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    client.patch(
        f"{API_SERVER_URL}{path}", json=json, params=params, headers=user.headers
    ).raise_for_status()


def _has_preferences_row(user: DATestUser) -> bool:
    with get_session_with_current_tenant() as db_session:
        return db_session.get(UserPreferences, UUID(user.id)) is not None


def test_new_user_reads_defaults_until_first_write(
    user_factory: Callable[[], DATestUser],
) -> None:
    user = user_factory()

    me = _me(user)
    assert me["preferences"] == DEFAULT_PREFERENCES
    personalization = me["personalization"]
    assert personalization["use_memories"] is True
    assert personalization["enable_memory_tool"] is True
    assert personalization["user_preferences"] == ""
    assert not _has_preferences_row(user)

    _patch(user, "/user/theme-preference", {"theme_preference": "dark"})

    assert _has_preferences_row(user)
    assert _me(user)["preferences"] == {
        **DEFAULT_PREFERENCES,
        "theme_preference": "dark",
    }


def test_every_setting_round_trips(
    user_factory: Callable[[], DATestUser],
) -> None:
    user = user_factory()

    _patch(user, "/temperature-default", {"temperature_default": 0.4})
    _patch(user, "/reasoning-effort-default", {"reasoning_effort_default": "high"})
    _patch(
        user,
        "/temperature-override-enabled",
        params={"temperature_override_enabled": True},
    )
    _patch(user, "/shortcut-enabled", params={"shortcut_enabled": True})
    _patch(user, "/paste-as-tile", params={"paste_as_tile": True})
    _patch(user, "/interrupt-on-send", params={"interrupt_on_send": True})
    _patch(user, "/auto-scroll", {"auto_scroll": False})
    _patch(user, "/user/theme-preference", {"theme_preference": "light"})
    _patch(user, "/user/language", {"language": "de"})
    _patch(user, "/user/chat-background", {"chat_background": "aurora"})
    _patch(user, "/user/default-app-mode", {"default_app_mode": "SEARCH"})
    _patch(
        user,
        "/user/appearance",
        {"interface_font": "atkinson", "response_font": "default"},
    )
    _patch(user, "/user/default-model", {"default_model": "P__openai__gpt-6-luna"})
    _patch(
        user,
        "/voice/settings",
        {"auto_send": True, "auto_playback": True, "playback_speed": 1.5},
    )
    _patch(user, "/user/assistant-list/update/7", params={"show": False})
    _patch(
        user,
        "/user/personalization",
        {
            "use_memories": False,
            "enable_memory_tool": False,
            "user_preferences": "Answer tersely.",
        },
    )

    me = _me(user)
    assert me["preferences"] == {
        **DEFAULT_PREFERENCES,
        "temperature_default": 0.4,
        "reasoning_effort_default": "high",
        "temperature_override_enabled": True,
        "shortcut_enabled": True,
        "paste_as_tile": True,
        "interrupt_on_send": True,
        "auto_scroll": False,
        "theme_preference": "light",
        "language": "de",
        "chat_background": "aurora",
        "default_app_mode": "SEARCH",
        "interface_font": "atkinson",
        "response_font": "default",
        "default_model": "P__openai__gpt-6-luna",
        "voice_auto_send": True,
        "voice_auto_playback": True,
        "voice_playback_speed": 1.5,
        "hidden_assistants": [7],
    }
    personalization = me["personalization"]
    assert personalization["use_memories"] is False
    assert personalization["enable_memory_tool"] is False
    assert personalization["user_preferences"] == "Answer tersely."

    # A partial personalization update keeps the other saved values, and a
    # null clears a nullable setting.
    _patch(user, "/user/personalization", {"use_memories": True})
    _patch(user, "/auto-scroll", {"auto_scroll": None})
    _patch(user, "/temperature-default", {"temperature_default": None})
    # A null voice setting keeps the saved value.
    _patch(user, "/voice/settings", {"auto_send": None, "auto_playback": False})
    # Playback speeds outside 0.5-2.0 are rejected.
    too_fast = client.patch(
        f"{API_SERVER_URL}/voice/settings",
        json={"playback_speed": 5.0},
        headers=user.headers,
    )
    assert too_fast.status_code == 422

    me = _me(user)
    assert me["preferences"]["auto_scroll"] is None
    assert me["preferences"]["temperature_default"] is None
    assert me["preferences"]["theme_preference"] == "light"
    assert me["preferences"]["voice_auto_send"] is True
    assert me["preferences"]["voice_auto_playback"] is False
    assert me["preferences"]["voice_playback_speed"] == 1.5
    personalization = me["personalization"]
    assert personalization["use_memories"] is True
    assert personalization["enable_memory_tool"] is False
    assert personalization["user_preferences"] == "Answer tersely."
