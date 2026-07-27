from collections.abc import Generator
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from onyx.auth import users
from onyx.auth.users import (
    current_chat_accessible_user,
    current_user_from_websocket,
    get_user_manager,
    optional_fastapi_current_user,
    optional_user,
)
from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.db.engine.async_sql_engine import get_async_session
from shared_configs.contextvars import CURRENT_USER_ID_CONTEXTVAR, get_current_user_id


def test_get_current_user_id_returns_set_value() -> None:
    token = CURRENT_USER_ID_CONTEXTVAR.set("user-123")
    try:
        assert get_current_user_id() == "user-123"
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)


def test_get_current_user_id_none_when_unset() -> None:
    # Background-worker case: no request context populated the var.
    assert get_current_user_id() is None


def test_reset_restores_previous_value() -> None:
    token = CURRENT_USER_ID_CONTEXTVAR.set("user-abc")
    CURRENT_USER_ID_CONTEXTVAR.reset(token)
    assert get_current_user_id() is None


def _authenticated_app(user_id: Any | None) -> FastAPI:
    class _FakeUser:
        id = user_id

    async def fake_auth() -> _FakeUser | None:
        return _FakeUser() if user_id is not None else None

    async def skip_oauth_refresh(*_: Any) -> None:
        return None

    def fake_dependency() -> object:
        return object()

    app = FastAPI()
    app.dependency_overrides[optional_fastapi_current_user] = fake_auth
    app.dependency_overrides[get_async_session] = fake_dependency
    app.dependency_overrides[get_user_manager] = fake_dependency
    app.state.skip_oauth_refresh = skip_oauth_refresh
    return app


def test_optional_user_context_propagates_to_streamed_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    app = _authenticated_app(user_id)
    monkeypatch.setattr(
        users,
        "_maybe_refresh_oauth_tokens",
        app.state.skip_oauth_refresh,
    )

    reads: list[str | None] = []

    @app.post("/stream")
    def stream_ep(
        _user: Any = Depends(optional_user),
    ) -> StreamingResponse:
        def gen() -> Generator[str, None, None]:
            for i in range(3):
                reads.append(get_current_user_id())
                yield f"chunk-{i}\n"

        return StreamingResponse(gen(), media_type="text/plain")

    client = TestClient(app)
    resp = client.post("/stream")

    assert resp.status_code == 200
    assert reads == [str(user_id)] * 3
    assert get_current_user_id() is None


def test_optional_user_context_is_set_for_endpoint_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    app = _authenticated_app(user_id)
    monkeypatch.setattr(
        users,
        "_maybe_refresh_oauth_tokens",
        app.state.skip_oauth_refresh,
    )

    @app.get("/plain")
    def plain_ep(
        _user: Any = Depends(optional_user),
    ) -> dict[str, Any]:
        return {"user_id": get_current_user_id()}

    client = TestClient(app)
    resp = client.get("/plain")

    assert resp.status_code == 200
    assert resp.json() == {"user_id": str(user_id)}
    assert get_current_user_id() is None


def test_anonymous_chat_context_propagates_to_streamed_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _authenticated_app(None)
    monkeypatch.setattr(users, "anonymous_user_enabled", lambda **_: True)
    reads: list[str | None] = []

    def chat_gate(
        _user: Any = Depends(current_chat_accessible_user),
    ) -> None:
        return None

    @app.post("/anonymous-stream")
    def stream_ep(
        _gate: None = Depends(chat_gate),
    ) -> StreamingResponse:
        def gen() -> Generator[str, None, None]:
            reads.append(get_current_user_id())
            yield "chunk\n"

        return StreamingResponse(gen(), media_type="text/plain")

    response = TestClient(app).post("/anonymous-stream")

    assert response.status_code == 200
    assert reads == [ANONYMOUS_USER_UUID]
    assert get_current_user_id() is None


@pytest.mark.asyncio
async def test_websocket_user_context_is_set_and_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()

    class _FakeUser:
        id = user_id
        email = "test@example.com"

    async def retrieve_token(_: str) -> dict[str, str]:
        return {"sub": str(user_id)}

    async def get_user(_: dict[str, str]) -> _FakeUser:
        return _FakeUser()

    async def check_user(user: _FakeUser) -> _FakeUser:
        return user

    monkeypatch.setattr(users, "is_same_origin", lambda *_: True)
    monkeypatch.setattr(users, "retrieve_ws_token_data", retrieve_token)
    monkeypatch.setattr(users, "_get_user_from_token_data", get_user)
    monkeypatch.setattr(users, "double_check_user", check_user)
    monkeypatch.setattr(users, "is_limited_user", lambda _: False)

    websocket = cast(WebSocket, type("_WebSocket", (), {"headers": {"origin": "x"}})())
    outer_token = CURRENT_USER_ID_CONTEXTVAR.set("outer-user")
    dependency = current_user_from_websocket(websocket, token="token")
    try:
        try:
            resolved_user = await anext(dependency)
            assert resolved_user.id == user_id
            assert get_current_user_id() == str(user_id)
        finally:
            await dependency.aclose()
        assert get_current_user_id() == "outer-user"
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(outer_token)
