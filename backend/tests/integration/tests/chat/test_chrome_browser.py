"""The user's Chrome as a chat browser, with a fake Onyx extension on the
real websocket (server/query_and_chat/chrome_browser.py), through the
integration test client.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import cast
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from onyx.browser_extension import relay
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import DATestUser


def _connect(token: str) -> WebSocketTestSession:
    """The extension's socket, through the test client (no server port)."""
    return cast(TestClient, client).websocket_connect(
        f"/chat/browser/extension/ws?token={token}"
    )


def _token(user: DATestUser) -> str:
    response = client.post(
        f"{API_SERVER_URL}/chat/browser/extension/token", headers=user.headers
    )
    response.raise_for_status()
    return response.json()["token"]


@contextmanager
def _extension(user: DATestUser) -> Iterator[WebSocketTestSession]:
    """A connected fake extension that said hello."""
    with _connect(_token(user)) as socket:
        socket.send_text(
            json.dumps(
                {
                    "type": "hello",
                    "installation_id": str(uuid4()),
                    "label": "Test Chrome",
                    "version": "1.3",
                }
            )
        )
        assert _next(socket, "welcome")["account"] == user.email
        yield socket


def _next(socket: WebSocketTestSession, kind: str) -> dict:
    """The next message of this kind, skipping pongs."""
    while True:
        message = json.loads(socket.receive_text())
        if message["type"] == kind:
            return message
        assert message["type"] == "pong", message


def _state(user: DATestUser, chat_id: str) -> dict:
    response = client.get(
        f"{API_SERVER_URL}/chat/sessions/{chat_id}/browser/chrome",
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _bind(user: DATestUser, chat_id: str, tab_id: int = 7) -> None:
    """What a turn from the extension's side panel does."""
    presence = relay.connected_installations(
        POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, UUID(user.id)
    )[0]
    relay.bind_chat(
        POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        UUID(user.id),
        UUID(chat_id),
        presence,
        chat_title="Chat",
        window_id=3,
        tab_id=tab_id,
        side_panel=True,
    )


def _tab_report(chat_id: str, tab_id: str = "7") -> str:
    return json.dumps(
        {
            "type": "grant",
            "grant": {
                "chat_session_id": chat_id,
                "tabs": [
                    {
                        "id": tab_id,
                        "title": "Wiki",
                        "url": "https://wiki.example/",
                        "origin": "https://wiki.example",
                    }
                ],
                "current": tab_id,
            },
        }
    )


def test_a_token_opens_one_socket(user_factory: Callable[[], DATestUser]) -> None:
    # Its own user: another test's socket cannot take its binds.
    user = user_factory()
    token = _token(user)
    with _connect(token) as socket:
        socket.send_text(json.dumps({"type": "hello", "installation_id": str(uuid4())}))
        assert _next(socket, "welcome")
    # Single use: the same token is refused.
    with pytest.raises(WebSocketDisconnect):
        with _connect(token) as socket:
            socket.receive_text()


def test_a_side_panel_bind_reaches_the_extension_and_stops(
    user_factory: Callable[[], DATestUser],
) -> None:
    user = user_factory()
    chat_id = str(ChatSessionManager.create(user_performing_action=user).id)
    with _extension(user) as socket:
        state = _state(user, chat_id)
        assert any(i["label"] == "Test Chrome" for i in state["installations"])
        assert state["grant"] is None

        _bind(user, chat_id)
        bind = _next(socket, "bind")
        assert bind["chat_session_id"] == chat_id
        assert bind["window_id"] == 3 and bind["tab_id"] == 7
        assert bind["side_panel"] is True

        socket.send_text(_tab_report(chat_id))
        assert _next(socket, "grant_saved")["chat_session_id"] == chat_id
        grant = _state(user, chat_id)["grant"]
        assert grant["side_panel"] is True
        assert grant["current"] == "7"
        assert grant["origins"] == []
        assert grant["tabs"][0]["origin"] == "https://wiki.example"

        # A stop in Onyx ends the grant and tells the extension.
        client.delete(
            f"{API_SERVER_URL}/chat/sessions/{chat_id}/browser/chrome",
            headers=user.headers,
        ).raise_for_status()
        assert _next(socket, "end_grant")["chat_session_id"] == chat_id
        assert _state(user, chat_id)["grant"] is None


def test_a_report_without_a_grant_ends_the_extensions_grant(
    user_factory: Callable[[], DATestUser],
) -> None:
    user = user_factory()
    chat_id = str(ChatSessionManager.create(user_performing_action=user).id)
    with _extension(user) as socket:
        socket.send_text(_tab_report(chat_id))
        assert _next(socket, "end_grant")["chat_session_id"] == chat_id
        assert _state(user, chat_id)["grant"] is None


def test_a_stop_in_the_extension_ends_the_grant(
    user_factory: Callable[[], DATestUser],
) -> None:
    user = user_factory()
    chat_id = str(ChatSessionManager.create(user_performing_action=user).id)
    with _extension(user) as socket:
        _bind(user, chat_id)
        _next(socket, "bind")
        socket.send_text(
            json.dumps({"type": "grant_ended", "chat_session_id": chat_id})
        )
        socket.send_text(json.dumps({"type": "ping"}))
        _next(socket, "pong")
        assert _state(user, chat_id)["grant"] is None


def test_one_installation_serves_one_chat(
    user_factory: Callable[[], DATestUser],
) -> None:
    user = user_factory()
    first = str(ChatSessionManager.create(user_performing_action=user).id)
    second = str(ChatSessionManager.create(user_performing_action=user).id)
    with _extension(user) as socket:
        for chat_id in (first, second):
            _bind(user, chat_id)
            _next(socket, "bind")
        assert _state(user, first)["grant"] is None
        assert _state(user, second)["grant"] is not None


def test_the_default_browser_preference_round_trips(
    user_factory: Callable[[], DATestUser],
) -> None:
    user = user_factory()

    def preference() -> str:
        me = client.get(f"{API_SERVER_URL}/me", headers=user.headers)
        me.raise_for_status()
        return me.json()["preferences"]["default_browser"]

    assert preference() == "SANDBOX"
    client.patch(
        f"{API_SERVER_URL}/user/default-browser",
        json={"default_browser": "CHROME"},
        headers=user.headers,
    ).raise_for_status()
    assert preference() == "CHROME"


def test_another_user_cannot_read_the_chat(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    chat_id = str(ChatSessionManager.create(user_performing_action=admin_user).id)
    response = client.get(
        f"{API_SERVER_URL}/chat/sessions/{chat_id}/browser/chrome",
        headers=basic_user.headers,
    )
    assert response.status_code == 404


def test_the_admin_switch_closes_the_socket(
    admin_user: DATestUser, user_factory: Callable[[], DATestUser]
) -> None:
    user = user_factory()

    def set_enabled(enabled: bool) -> None:
        client.patch(
            f"{API_SERVER_URL}/admin/settings",
            json={"chrome_browser_enabled": enabled},
            headers=admin_user.headers,
        ).raise_for_status()

    settings = client.get(f"{API_SERVER_URL}/settings", headers=admin_user.headers)
    settings.raise_for_status()
    previous = settings.json().get("chrome_browser_enabled", True)
    set_enabled(True)
    try:
        with _extension(user) as socket:
            set_enabled(False)
            socket.send_text(json.dumps({"type": "ping"}))
            with pytest.raises(WebSocketDisconnect) as closed:
                _next(socket, "never")
            assert closed.value.code == 4403
        response = client.post(
            f"{API_SERVER_URL}/chat/browser/extension/token",
            headers=user.headers,
        )
        assert response.status_code == 403
    finally:
        set_enabled(previous)
