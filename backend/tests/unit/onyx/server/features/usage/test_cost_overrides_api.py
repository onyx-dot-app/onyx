"""Admin cost-override CRUD: upsert is idempotent, GET reflects writes, DELETE
removes (404 on missing), non-admins are rejected, and every write busts the
per-tenant override cache."""

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
from onyx.db.models import ModelCostOverride
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.llm import cost_overrides
from onyx.llm.cost_overrides import delete_override
from onyx.llm.cost_overrides import list_overrides
from onyx.llm.cost_overrides import upsert_override
from onyx.server.features.usage.api import router as cost_override_router


class _StubUser:
    """Minimal stand-in for User: require_permission only reads these two."""

    def __init__(self, permissions: list[str]) -> None:
        self.id = "00000000-0000-0000-0000-000000000001"
        self.effective_permissions = permissions


_ADMIN = _StubUser([Permission.FULL_ADMIN_PANEL_ACCESS.value])
_NON_ADMIN = _StubUser([])


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    # StaticPool shares one in-memory connection so the table survives the
    # endpoint's commit() (which otherwise returns the connection to the pool
    # and the next checkout would hit a fresh, empty :memory: database).
    engine: Engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    table = cast(Table, ModelCostOverride.__table__)
    table.create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_app(db_session: Session, user: _StubUser) -> FastAPI:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(cost_override_router)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[current_user] = lambda: user
    return app


def test_upsert_creates_then_updates_and_lists(db_session: Session) -> None:
    client = TestClient(_make_app(db_session, _ADMIN))

    create = client.put(
        "/admin/cost-overrides",
        json={
            "model": "gpt-4o",
            "input_cost_per_mtok": 2.5,
            "output_cost_per_mtok": 10.0,
        },
    )
    assert create.status_code == 200
    assert create.json()["input_cost_per_mtok"] == 2.5

    # Same model again updates in place rather than duplicating.
    update = client.put(
        "/admin/cost-overrides",
        json={
            "model": "gpt-4o",
            "input_cost_per_mtok": 1.0,
            "output_cost_per_mtok": 4.0,
        },
    )
    assert update.status_code == 200
    assert update.json()["output_cost_per_mtok"] == 4.0

    listing = client.get("/admin/cost-overrides")
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["model"] == "gpt-4o"
    assert rows[0]["input_cost_per_mtok"] == 1.0


def test_delete_removes_then_404(db_session: Session) -> None:
    client = TestClient(_make_app(db_session, _ADMIN))
    client.put(
        "/admin/cost-overrides",
        json={
            "model": "claude-haiku-4-5",
            "input_cost_per_mtok": 0.8,
            "output_cost_per_mtok": 4.0,
        },
    )

    deleted = client.delete("/admin/cost-overrides/claude-haiku-4-5")
    assert deleted.status_code == 200
    assert client.get("/admin/cost-overrides").json() == []

    missing = client.delete("/admin/cost-overrides/claude-haiku-4-5")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "NOT_FOUND"


def test_non_admin_rejected(db_session: Session) -> None:
    client = TestClient(_make_app(db_session, _NON_ADMIN))
    resp = client.put(
        "/admin/cost-overrides",
        json={
            "model": "gpt-4o",
            "input_cost_per_mtok": 2.5,
            "output_cost_per_mtok": 10.0,
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "INSUFFICIENT_PERMISSIONS"


def test_writes_invalidate_cache(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        "onyx.server.features.usage.api.invalidate_override_cache",
        lambda: calls.append(1),
    )
    client = TestClient(_make_app(db_session, _ADMIN))

    client.put(
        "/admin/cost-overrides",
        json={
            "model": "gpt-4o",
            "input_cost_per_mtok": 2.5,
            "output_cost_per_mtok": 10.0,
        },
    )
    assert len(calls) == 1

    client.delete("/admin/cost-overrides/gpt-4o")
    assert len(calls) == 2


def test_db_helpers_upsert_list_delete(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cost_overrides, "get_current_tenant_id", lambda: "public", raising=False
    )

    upsert_override(db_session, "gpt-4o", 2.5, 10.0)
    upsert_override(db_session, "claude-haiku-4-5", 0.8, 4.0)
    upsert_override(db_session, "gpt-4o", 1.0, 4.0)  # update, not insert

    rows = list_overrides(db_session)
    assert [r.model for r in rows] == ["claude-haiku-4-5", "gpt-4o"]  # name-ordered
    gpt = next(r for r in rows if r.model == "gpt-4o")
    assert gpt.input_cost_per_mtok == 1.0

    assert delete_override(db_session, "gpt-4o") is True
    assert delete_override(db_session, "gpt-4o") is False
    assert [r.model for r in list_overrides(db_session)] == ["claude-haiku-4-5"]


def test_negative_rate_rejected_by_api(db_session: Session) -> None:
    # A negative rate would credit usage and corrupt budgets; the request model
    # enforces ge=0, so the endpoint rejects it before any write.
    client = TestClient(_make_app(db_session, _ADMIN))
    res = client.put(
        "/admin/cost-overrides",
        json={
            "model": "gpt-4o",
            "input_cost_per_mtok": -1.0,
            "output_cost_per_mtok": 4.0,
        },
    )
    assert res.status_code == 422
    assert list_overrides(db_session) == []


def test_db_helper_rejects_negative_rate(db_session: Session) -> None:
    with pytest.raises(ValueError):
        upsert_override(db_session, "gpt-4o", -1.0, 4.0)
