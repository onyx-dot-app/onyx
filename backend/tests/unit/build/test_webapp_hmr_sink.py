from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from onyx.server.features.build.api import api


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.closed_code: int | None = None
        self.receive_calls = 0

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int) -> None:
        self.closed_code = code

    async def receive_text(self) -> str:
        self.receive_calls += 1
        if self.receive_calls == 1:
            return "ping"
        raise WebSocketDisconnect()


@pytest.mark.asyncio
async def test_hmr_sink_consumes_client_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket()

    def allow_access(_session_id: object, _user: object, _db_session: object) -> None:
        return None

    monkeypatch.setattr(api, "_check_webapp_access", allow_access)

    async def fail_if_sink_idles(_: float) -> None:
        raise AssertionError("HMR sink idled instead of consuming websocket messages")

    monkeypatch.setattr(api.asyncio, "sleep", fail_if_sink_idles)

    await api._hmr_websocket_sink(
        websocket,
        uuid4(),
        user=None,
        db_session=SimpleNamespace(),
    )

    assert websocket.accepted is True
    assert websocket.receive_calls >= 1


@pytest.mark.asyncio
async def test_hmr_sink_rejects_unauthorized_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket()

    def raise_access_error(
        _session_id: object, _user: object, _db_session: object
    ) -> None:
        raise RuntimeError("denied")

    monkeypatch.setattr(api, "_check_webapp_access", raise_access_error)

    await api._hmr_websocket_sink(
        websocket,
        uuid4(),
        user=None,
        db_session=SimpleNamespace(),
    )

    assert websocket.accepted is False
    assert websocket.closed_code == 4003
