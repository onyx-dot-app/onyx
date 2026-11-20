"""The backend owns the appearance cookie the web server layout reads to
render the saved fonts and motion on first paint: PATCH /user/appearance sets
it and GET /me reissues it when the browser's copy is missing or stale."""

from collections.abc import Callable
from urllib.parse import parse_qs, quote, unquote, urlencode

import httpx

from onyx.configs.constants import APPEARANCE_COOKIE_NAME
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.settings import SettingsManager
from tests.integration.common_utils.test_models import DATestUser


def _appearance_cookie(response: httpx.Response) -> dict[str, list[str]] | None:
    cookie = response.cookies.get(APPEARANCE_COOKIE_NAME)
    return None if cookie is None else parse_qs(unquote(cookie))


def _cookie_value(interface_font: str, response_font: str, motion: str) -> str:
    return quote(
        urlencode(
            {
                "interface_font": interface_font,
                "response_font": response_font,
                "motion": motion,
            }
        )
    )


def _with_appearance_cookie(
    user: DATestUser, appearance_cookie: str | None
) -> dict[str, str]:
    headers = dict(user.headers)
    if appearance_cookie is not None:
        # The client's cookie jar is skipped when a request has a Cookie
        # header, so the appearance cookie joins the auth cookie there.
        headers["Cookie"] = (
            f"{headers['Cookie']}; {APPEARANCE_COOKIE_NAME}={appearance_cookie}"
        )
    return headers


def _me(user: DATestUser, appearance_cookie: str | None = None) -> httpx.Response:
    response = client.get(
        f"{API_SERVER_URL}/me", headers=_with_appearance_cookie(user, appearance_cookie)
    )
    response.raise_for_status()
    return response


def _set_anonymous_access(admin_user: DATestUser, enabled: bool) -> None:
    client.patch(
        f"{API_SERVER_URL}/admin/settings",
        json={"anonymous_user_enabled": enabled},
        headers=admin_user.headers,
    ).raise_for_status()


def test_appearance_save_reaches_me_and_cookie(
    user_factory: Callable[[], DATestUser],
) -> None:
    user = user_factory()

    # A new user gets the defaults, in the preferences and in the cookie.
    fresh = _me(user)
    assert fresh.json()["preferences"]["interface_font"] == "default"
    assert fresh.json()["preferences"]["response_font"] == "match"
    assert fresh.json()["preferences"]["motion"] == "system"
    assert _appearance_cookie(fresh) == {
        "interface_font": ["default"],
        "response_font": ["match"],
        "motion": ["system"],
    }

    # A partial save keeps the other field and returns the full cookie.
    saved = client.patch(
        f"{API_SERVER_URL}/user/appearance",
        json={"interface_font": "opendyslexic"},
        headers=user.headers,
    )
    saved.raise_for_status()
    expected = {
        "interface_font": ["opendyslexic"],
        "response_font": ["match"],
        "motion": ["system"],
    }
    assert _appearance_cookie(saved) == expected

    me = _me(user)
    assert me.json()["preferences"]["interface_font"] == "opendyslexic"
    assert me.json()["preferences"]["response_font"] == "match"
    assert _appearance_cookie(me) == expected

    # A stale cookie is reissued; a current one is left alone.
    stale = _me(user, _cookie_value("default", "match", "system"))
    assert _appearance_cookie(stale) == expected
    assert (
        _appearance_cookie(_me(user, _cookie_value("opendyslexic", "match", "system")))
        is None
    )

    # Motion rides the same cookie; settings without a first-paint effect
    # save without changing it.
    reduced = client.patch(
        f"{API_SERVER_URL}/user/appearance",
        json={"motion": "reduced"},
        headers=user.headers,
    )
    reduced.raise_for_status()
    assert _appearance_cookie(reduced) == {
        "interface_font": ["opendyslexic"],
        "response_font": ["match"],
        "motion": ["reduced"],
    }
    popups = client.patch(
        f"{API_SERVER_URL}/user/appearance",
        json={"popup_dismissal": "stay_on_screen", "dynamic_conversations": False},
        headers=_with_appearance_cookie(
            user, _cookie_value("opendyslexic", "match", "reduced")
        ),
    )
    popups.raise_for_status()
    assert _appearance_cookie(popups) is None
    saved_preferences = _me(user).json()["preferences"]
    assert saved_preferences["motion"] == "reduced"
    assert saved_preferences["popup_dismissal"] == "stay_on_screen"
    assert saved_preferences["dynamic_conversations"] is False

    # The server rejects a value outside the options.
    invalid = client.patch(
        f"{API_SERVER_URL}/user/appearance",
        json={"interface_font": "comic-sans"},
        headers=user.headers,
    )
    assert invalid.status_code == 422
    assert _me(user).json()["preferences"]["interface_font"] == "opendyslexic"
    invalid_motion = client.patch(
        f"{API_SERVER_URL}/user/appearance",
        json={"motion": "none"},
        headers=user.headers,
    )
    assert invalid_motion.status_code == 422
    assert _me(user).json()["preferences"]["motion"] == "reduced"


def test_anonymous_me_returns_default_appearance(admin_user: DATestUser) -> None:
    settings, settings_error = SettingsManager.get_settings(admin_user)
    assert not settings_error, settings_error
    # Unset means disabled.
    was_enabled = bool(settings.get("anonymous_user_enabled"))
    _set_anonymous_access(admin_user, True)
    try:
        # A browser that still carries a signed-out user's cookie is moved
        # back to the column defaults, in the preferences and in the cookie.
        anonymous = client.get(
            f"{API_SERVER_URL}/me",
            headers={
                "Cookie": f"{APPEARANCE_COOKIE_NAME}="
                f"{_cookie_value('opendyslexic', 'default', 'reduced')}"
            },
        )
        anonymous.raise_for_status()
        assert anonymous.json()["is_anonymous_user"] is True
        preferences = anonymous.json()["preferences"]
        assert preferences["interface_font"] == "default"
        assert preferences["response_font"] == "match"
        assert preferences["motion"] == "system"
        assert preferences["popup_dismissal"] == "auto_dismiss"
        assert preferences["dynamic_conversations"] is True
        assert _appearance_cookie(anonymous) == {
            "interface_font": ["default"],
            "response_font": ["match"],
            "motion": ["system"],
        }
    finally:
        # The settings record is cached outside the database, so later tests
        # would otherwise inherit anonymous access.
        _set_anonymous_access(admin_user, was_enabled)
