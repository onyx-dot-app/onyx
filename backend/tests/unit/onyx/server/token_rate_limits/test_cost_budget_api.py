"""Global token-rate-limit create/read round-trips cost_budget_cents (cents at
the API boundary), and a limit may carry only a cost budget (no token budget)."""

from collections.abc import Generator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import Table
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import TokenRateLimit
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.token_rate_limits.api import router as token_rate_limit_router


class _StubUser:
    def __init__(self, permissions: list[str]) -> None:
        self.id = "00000000-0000-0000-0000-000000000001"
        self.effective_permissions = permissions


_ADMIN = _StubUser([Permission.FULL_ADMIN_PANEL_ACCESS.value])


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    # StaticPool keeps the table alive across the endpoint's commit().
    engine: Engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    cast(Table, TokenRateLimit.__table__).create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_app(db_session: Session) -> FastAPI:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(token_rate_limit_router)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[current_user] = lambda: _ADMIN
    return app


def test_create_persists_cost_budget_and_get_returns_it(db_session: Session) -> None:
    client = TestClient(_make_app(db_session))

    created = client.post(
        "/admin/token-rate-limits/global",
        json={
            "enabled": True,
            "token_budget": 1000,
            "period_hours": 24,
            "cost_budget_cents": 500.0,
        },
    )
    assert created.status_code == 200
    assert created.json()["cost_budget_cents"] == 500.0

    listing = client.get("/admin/token-rate-limits/global")
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["cost_budget_cents"] == 500.0
    assert rows[0]["token_budget"] == 1000


def test_cost_budget_optional_defaults_null(db_session: Session) -> None:
    client = TestClient(_make_app(db_session))

    created = client.post(
        "/admin/token-rate-limits/global",
        json={"enabled": True, "token_budget": 1000, "period_hours": 24},
    )
    assert created.status_code == 200
    assert created.json()["cost_budget_cents"] is None
