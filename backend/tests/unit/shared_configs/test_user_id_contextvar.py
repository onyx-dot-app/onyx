from collections.abc import Generator
from typing import Any
from uuid import uuid4

from fastapi import Depends
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from onyx.server.utils import set_current_user_id_dependency
from shared_configs.contextvars import CURRENT_USER_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_user_id


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


def test_user_id_propagates_to_every_streamed_chunk() -> None:
    """Drives the real StreamingResponse / iterate_in_threadpool path.

    The user id must be readable on every iteration (not just the first), since
    LLM calls and usage recording happen throughout the stream. Also asserts the
    var resets to None after the request without raising.
    """
    user_id = uuid4()

    class _FakeUser:
        id = user_id

    async def fake_auth() -> _FakeUser:
        return _FakeUser()

    app = FastAPI()
    reads: list[str | None] = []

    @app.post("/stream")
    def stream_ep(
        _user_ctx: None = Depends(set_current_user_id_dependency(fake_auth)),
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
    # No leak / no different-context reset error after the request finishes.
    assert get_current_user_id() is None


def test_user_id_set_for_non_streaming_endpoint_body() -> None:
    """The dependency also covers the non-streaming / multi-model branches that
    read the var synchronously in the endpoint body."""
    user_id = uuid4()

    class _FakeUser:
        id = user_id

    async def fake_auth() -> _FakeUser:
        return _FakeUser()

    app = FastAPI()

    @app.get("/plain")
    def plain_ep(
        _user_ctx: None = Depends(set_current_user_id_dependency(fake_auth)),
    ) -> dict[str, Any]:
        return {"user_id": get_current_user_id()}

    client = TestClient(app)
    resp = client.get("/plain")

    assert resp.status_code == 200
    assert resp.json() == {"user_id": str(user_id)}
    assert get_current_user_id() is None
