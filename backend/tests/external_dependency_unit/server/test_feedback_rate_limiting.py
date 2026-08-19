"""Tests for the per-user rate limiting applied to the chat message feedback
endpoints (ON-009). Uses a real Redis connection via the centralized pool —
the FastAPI app is a minimal stand-in for the real router, with auth
dependency-overridden to control the resolved user."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_limiter import FastAPILimiter

from onyx.auth.users import current_chat_accessible_user
from onyx.configs.app_configs import FEEDBACK_RATE_LIMIT_MAX_REQUESTS
from onyx.db.enums import AccountType
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.server.middleware.rate_limiting import get_feedback_rate_limiters


def _fake_user(account_type: AccountType = AccountType.STANDARD) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), account_type=account_type)


def _build_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        redis = await get_async_redis_connection()
        await FastAPILimiter.init(redis)
        yield
        await FastAPILimiter.close()

    app = FastAPI(lifespan=lifespan)

    # The real dependency list used by the feedback endpoints
    @app.post("/feedback", dependencies=get_feedback_rate_limiters())
    def feedback() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_feedback_rate_limit_blocks_flood_for_same_user() -> None:
    app = _build_app()
    user = _fake_user()
    app.dependency_overrides[current_chat_accessible_user] = lambda: user

    with TestClient(app) as client:
        for _ in range(FEEDBACK_RATE_LIMIT_MAX_REQUESTS):
            response = client.post("/feedback")
            assert response.status_code == 200

        response = client.post("/feedback")
        assert response.status_code == 429


def test_feedback_rate_limit_separate_users_have_separate_buckets() -> None:
    app = _build_app()
    first_user = _fake_user()
    second_user = _fake_user()

    with TestClient(app) as client:
        app.dependency_overrides[current_chat_accessible_user] = lambda: first_user
        for _ in range(FEEDBACK_RATE_LIMIT_MAX_REQUESTS):
            assert client.post("/feedback").status_code == 200
        assert client.post("/feedback").status_code == 429

        # A different user is not affected by the first user's flood
        app.dependency_overrides[current_chat_accessible_user] = lambda: second_user
        assert client.post("/feedback").status_code == 200


def test_feedback_rate_limit_same_user_cannot_reset_via_new_session() -> None:
    """Keying is on the user id, not the session credential — re-logging-in
    (new cookie) must not grant a fresh budget."""
    app = _build_app()
    user = _fake_user()
    app.dependency_overrides[current_chat_accessible_user] = lambda: user

    with TestClient(app) as client:
        for _ in range(FEEDBACK_RATE_LIMIT_MAX_REQUESTS):
            assert (
                client.post(
                    "/feedback", cookies={"fastapiusersauth": str(uuid.uuid4())}
                ).status_code
                == 200
            )

        # Fresh cookie value, same user -> still over the limit
        assert (
            client.post(
                "/feedback", cookies={"fastapiusersauth": str(uuid.uuid4())}
            ).status_code
            == 429
        )
