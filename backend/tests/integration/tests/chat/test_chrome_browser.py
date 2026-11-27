"""The user's Chrome as a chat browser, against a running deployment, with a
fake Onyx extension on the real websocket (server/query_and_chat/chrome_browser.py).
"""

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import ClientConnection, connect
from websockets.sync.connection import Connection

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import DATestUser

_WS_URL = API_SERVER_URL.replace("http", "ws", 1)
_WAIT_SECONDS = 10


def _token(user: DATestUser) -> str:
    response = client.post(
        f"{API_SERVER_URL}/chat/browser/extension/token", headers=user.headers
    )
    response.raise_for_status()
    return response.json()["token"]


@contextmanager
def _extension(user: DATestUser) -> Iterator[ClientConnection]:
    """A connected fake extension that said hello."""
    socket = connect(f"{_WS_URL}/chat/browser/extension/ws?token={_token(user)}")
    try:
        socket.send(
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
    finally:
        socket.close()


def _next(socket: Connection, kind: str) -> dict:
    """The next message of this kind, skipping pongs."""
    deadline = time.monotonic() + _WAIT_SECONDS
    while True:
        message = json.loads(socket.recv(timeout=deadline - time.monotonic()))
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


def test_a_token_opens_one_socket(admin_user: DATestUser) -> None:
    token = _token(admin_user)
    with connect(f"{_WS_URL}/chat/browser/extension/ws?token={token}") as socket:
        socket.send(json.dumps({"type": "hello", "installation_id": str(uuid4())}))
        assert _next(socket, "welcome")
    # Single use: the same token is refused.
    with pytest.raises((InvalidStatus, ConnectionClosed)):
        with connect(f"{_WS_URL}/chat/browser/extension/ws?token={token}") as socket:
            socket.recv(timeout=_WAIT_SECONDS)


def test_share_approve_and_stop(admin_user: DATestUser) -> None:
    chat_id = str(ChatSessionManager.create(user_performing_action=admin_user).id)
    with _extension(admin_user) as socket:
        state = _state(admin_user, chat_id)
        assert any(i["label"] == "Test Chrome" for i in state["installations"])
        assert state["grant"] is None

        _request(admin_user, chat_id)
        request = _next(socket, "grant_request")
        assert request["chat_session_id"] == chat_id
        assert _state(admin_user, chat_id)["request"] == "pending"

        # A report for a request that this installation never got is refused.
        socket.send(_grant_report(chat_id, uuid4().hex))
        assert _next(socket, "end_grant")["chat_session_id"] == chat_id
        assert _state(admin_user, chat_id)["grant"] is None

        socket.send(_grant_report(chat_id, request["request_id"]))
        assert _next(socket, "grant_saved")["chat_session_id"] == chat_id
        grant = _state(admin_user, chat_id)["grant"]
        assert grant["origins"] == ["https://wiki.example"]
        assert grant["tabs"][0]["title"] == "Wiki"

        # A stop in Onyx ends the grant and tells the extension.
        client.delete(
            f"{API_SERVER_URL}/chat/sessions/{chat_id}/browser/chrome",
            headers=admin_user.headers,
        ).raise_for_status()
        assert _next(socket, "end_grant")["chat_session_id"] == chat_id
        assert _state(admin_user, chat_id)["grant"] is None


def test_deny_and_a_stop_in_the_extension(admin_user: DATestUser) -> None:
    chat_id = str(ChatSessionManager.create(user_performing_action=admin_user).id)
    with _extension(admin_user) as socket:
        _request(admin_user, chat_id)
        request = _next(socket, "grant_request")
        socket.send(
            json.dumps(
                {
                    "type": "grant_denied",
                    "chat_session_id": chat_id,
                    "request_id": request["request_id"],
                }
            )
        )
        socket.send(json.dumps({"type": "ping"}))
        _next(socket, "pong")
        assert _state(admin_user, chat_id)["request"] == "denied"

        _request(admin_user, chat_id)
        request = _next(socket, "grant_request")
        socket.send(_grant_report(chat_id, request["request_id"]))
        _next(socket, "grant_saved")
        socket.send(json.dumps({"type": "grant_ended", "chat_session_id": chat_id}))
        socket.send(json.dumps({"type": "ping"}))
        _next(socket, "pong")
        assert _state(admin_user, chat_id)["grant"] is None


def test_one_installation_serves_one_chat(admin_user: DATestUser) -> None:
    first = str(ChatSessionManager.create(user_performing_action=admin_user).id)
    second = str(ChatSessionManager.create(user_performing_action=admin_user).id)
    with _extension(admin_user) as socket:
        for chat_id in (first, second):
            _request(admin_user, chat_id)
            request = _next(socket, "grant_request")
            socket.send(_grant_report(chat_id, request["request_id"]))
            _next(socket, "grant_saved")
        assert _state(admin_user, first)["grant"] is None
        assert _state(admin_user, second)["grant"] is not None


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


def test_the_admin_switch_closes_the_socket(admin_user: DATestUser) -> None:
    def set_enabled(enabled: bool) -> None:
        client.patch(
            f"{API_SERVER_URL}/admin/settings",
            json={"chrome_browser_enabled": enabled},
            headers=admin_user.headers,
        ).raise_for_status()

    try:
        with _extension(admin_user) as socket:
            set_enabled(False)
            socket.send(json.dumps({"type": "ping"}))
            with pytest.raises(ConnectionClosed) as closed:
                _next(socket, "never")
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == 4403
        response = client.post(
            f"{API_SERVER_URL}/chat/browser/extension/token",
            headers=admin_user.headers,
        )
        assert response.status_code == 403
    finally:
        set_enabled(True)
