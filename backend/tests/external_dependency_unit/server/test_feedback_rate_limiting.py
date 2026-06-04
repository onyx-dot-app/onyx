"""Tests for the per-credential rate limiting applied to the chat message
feedback endpoints (ON-009). Uses a real Redis connection via the centralized
pool — only the FastAPI app is a minimal stand-in for the real router."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.server.middleware.rate_limiting import user_rate_limit_key

_LIMIT_TIMES = 3
_LIMIT_WINDOW_SECONDS = 60


def _build_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        redis = await get_async_redis_connection()
        await FastAPILimiter.init(redis)
        yield
        await FastAPILimiter.close()

    app = FastAPI(lifespan=lifespan)

    # Same shape as get_feedback_rate_limiters(), but with a small limit so
    # the test doesn't need to fire 30 requests.
    @app.post(
        "/feedback",
        dependencies=[
            Depends(
                RateLimiter(
                    times=_LIMIT_TIMES,
                    seconds=_LIMIT_WINDOW_SECONDS,
                    identifier=user_rate_limit_key,
                )
            )
        ],
    )
    def feedback() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _session_cookie() -> dict[str, str]:
    # Unique per call so test runs never collide with a stale window
    return {FASTAPI_USERS_AUTH_COOKIE_NAME: f"test-session-{uuid.uuid4()}"}


def test_feedback_rate_limit_blocks_flood_for_same_session() -> None:
    app = _build_app()
    cookies = _session_cookie()

    with TestClient(app) as client:
        for _ in range(_LIMIT_TIMES):
            response = client.post("/feedback", cookies=cookies)
            assert response.status_code == 200

        response = client.post("/feedback", cookies=cookies)
        assert response.status_code == 429


def test_feedback_rate_limit_separate_sessions_have_separate_buckets() -> None:
    app = _build_app()
    first_session = _session_cookie()
    second_session = _session_cookie()

    with TestClient(app) as client:
        for _ in range(_LIMIT_TIMES):
            assert client.post("/feedback", cookies=first_session).status_code == 200
        assert client.post("/feedback", cookies=first_session).status_code == 429

        # A different session is not affected by the first session's flood
        assert client.post("/feedback", cookies=second_session).status_code == 200
