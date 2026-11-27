"""The user's Chrome as a chat browser, with a fake Onyx extension on the
real websocket (server/query_and_chat/chrome_browser.py), through the
integration test client.
"""

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import cast
from uuid import uuid4

import pytest
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

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


def _request(user: DATestUser, chat_id: str) -> None:
    client.post(
        f"{API_SERVER_URL}/chat/sessions/{chat_id}/browser/chrome",
        json={},
        headers=user.headers,
    ).raise_for_status()


def _grant_report(chat_id: str, request_id: str | None) -> str:
    return json.dumps(
        {
            "type": "grant",
            "grant": {
                "chat_session_id": chat_id,
                "request_id": request_id,
                "tabs": [{"id": "7", "title": "Wiki", "url": "https://wiki.example/"}],
                "origins": ["https://wiki.example"],
                "expires_at": time.time() + 600,
            },
        }
    )


def test_a_token_opens_one_socket(user_factory: Callable[[], DATestUser]) -> None:
    # Its own user: another test's socket cannot take its share requests.
    user = user_factory()
    token = _token(user)
    with _connect(token) as socket:
        socket.send_text(json.dumps({"type": "hello", "installation_id": str(uuid4())}))
        assert _next(socket, "welcome")
    # Single use: the same token is refused.
    with pytest.raises(WebSocketDisconnect):
        with _connect(token) as socket:
            socket.receive_text()


def test_share_approve_and_stop(user_factory: Callable[[], DATestUser]) -> None:
    # Its own user: another test's socket cannot take its share requests.
    user = user_factory()
    chat_id = str(ChatSessionManager.create(user_performing_action=user).id)
    with _extension(user) as socket:
        state = _state(user, chat_id)
        assert any(i["label"] == "Test Chrome" for i in state["installations"])
        assert state["grant"] is None

        _request(user, chat_id)
        request = _next(socket, "grant_request")
        assert request["chat_session_id"] == chat_id
        assert _state(user, chat_id)["request"] == "pending"

        # A report for a request that this installation never got is refused.
        socket.send_text(_grant_report(chat_id, uuid4().hex))
        assert _next(socket, "end_grant")["chat_session_id"] == chat_id
        assert _state(user, chat_id)["grant"] is None

        socket.send_text(_grant_report(chat_id, request["request_id"]))
        assert _next(socket, "grant_saved")["chat_session_id"] == chat_id
        grant = _state(user, chat_id)["grant"]
        assert grant["origins"] == ["https://wiki.example"]
        assert grant["tabs"][0]["title"] == "Wiki"

        # A stop in Onyx ends the grant and tells the extension.
        client.delete(
            f"{API_SERVER_URL}/chat/sessions/{chat_id}/browser/chrome",
            headers=user.headers,
        ).raise_for_status()
        assert _next(socket, "end_grant")["chat_session_id"] == chat_id
        assert _state(user, chat_id)["grant"] is None


def test_deny_and_a_stop_in_the_extension(
    user_factory: Callable[[], DATestUser],
) -> None:
    # Its own user: another test's socket cannot take its share requests.
    user = user_factory()
    chat_id = str(ChatSessionManager.create(user_performing_action=user).id)
    with _extension(user) as socket:
        _request(user, chat_id)
        request = _next(socket, "grant_request")
        socket.send_text(
            json.dumps(
                {
                    "type": "grant_denied",
                    "chat_session_id": chat_id,
                    "request_id": request["request_id"],
                }
            )
        )
        socket.send_text(json.dumps({"type": "ping"}))
        _next(socket, "pong")
        assert _state(user, chat_id)["request"] == "denied"

        _request(user, chat_id)
        request = _next(socket, "grant_request")
        socket.send_text(_grant_report(chat_id, request["request_id"]))
        _next(socket, "grant_saved")
        socket.send_text(
            json.dumps({"type": "grant_ended", "chat_session_id": chat_id})
        )
        socket.send_text(json.dumps({"type": "ping"}))
        _next(socket, "pong")
        assert _state(user, chat_id)["grant"] is None


def test_one_installation_serves_one_chat(
    user_factory: Callable[[], DATestUser],
) -> None:
    # Its own user: another test's socket cannot take its share requests.
    user = user_factory()
    first = str(ChatSessionManager.create(user_performing_action=user).id)
    second = str(ChatSessionManager.create(user_performing_action=user).id)
    with _extension(user) as socket:
        for chat_id in (first, second):
            _request(user, chat_id)
            request = _next(socket, "grant_request")
            socket.send_text(_grant_report(chat_id, request["request_id"]))
            _next(socket, "grant_saved")
        assert _state(user, first)["grant"] is None
        assert _state(user, second)["grant"] is not None


def test_another_user_cannot_read_or_share_the_chat(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    chat_id = str(ChatSessionManager.create(user_performing_action=admin_user).id)
    response = client.post(
        f"{API_SERVER_URL}/chat/sessions/{chat_id}/browser/chrome",
        json={},
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
