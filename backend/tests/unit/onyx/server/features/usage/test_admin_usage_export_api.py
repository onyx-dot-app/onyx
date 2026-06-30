"""Admin /admin/usage/export: tenant-wide usage joined to email, grouped per
(email x model x window-day) with a per-user totals roll-up, the model filter
narrows results, the date range bounds half-open, and non-admins are rejected.

Also unit-tests the get_usage_export DB helper directly."""

import datetime
from collections.abc import Generator
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import Table
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import UserUsage
from onyx.db.user_usage import get_usage_export
from onyx.db.user_usage import record_user_usage
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.features.usage.api import admin_usage_router


@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "JSON"


class _StubUser:
    """require_permission only reads effective_permissions; the JOIN target is
    the separately-created `user` table, not this auth stub."""

    def __init__(self, permissions: list[str]) -> None:
        self.id = "00000000-0000-0000-0000-000000000001"
        self.effective_permissions = permissions


_ADMIN = _StubUser([Permission.FULL_ADMIN_PANEL_ACCESS.value])
_NON_ADMIN = _StubUser([])


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    cast(Table, UserUsage.__table__).create(bind=engine)
    # Minimal `user` table: the export JOIN only touches id + email.
    with engine.begin() as conn:
        conn.execute(
            text('CREATE TABLE "user" (id CHAR(36) PRIMARY KEY, email VARCHAR)')
        )
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _add_user(db_session: Session, email: str) -> str:
    user_id = str(uuid4())
    db_session.execute(
        text('INSERT INTO "user" (id, email) VALUES (:id, :email)'),
        {"id": user_id, "email": email},
    )
    return user_id


def _make_app(db_session: Session, user: _StubUser) -> FastAPI:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(admin_usage_router)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[current_user] = lambda: user
    return app


_W1 = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)  # Monday
_W2 = datetime.datetime(2026, 6, 8, tzinfo=datetime.timezone.utc)  # next Monday


def _seed_two_users(db_session: Session) -> tuple[str, str]:
    """alice: model-a in W1 + W2, model-b in W1.  bob: model-a in W2."""
    alice = _add_user(db_session, "alice@example.com")
    bob = _add_user(db_session, "bob@example.com")

    record_user_usage(
        db_session, alice, "model-a", "CHAT", "openai", 100, 50, 5, 1.0, _W1
    )
    record_user_usage(
        db_session, alice, "model-b", "CHAT", "openai", 200, 60, 0, 2.0, _W1
    )
    record_user_usage(
        db_session, alice, "model-a", "CHAT", "openai", 300, 70, 0, 3.0, _W2
    )
    record_user_usage(
        db_session, bob, "model-a", "CHAT", "anthropic", 400, 80, 0, 4.0, _W2
    )
    db_session.commit()
    return alice, bob


class TestGetUsageExportHelper:
    def test_groups_by_email_model_day_with_join(self, db_session: Session) -> None:
        _seed_two_users(db_session)
        rows = get_usage_export(
            db_session,
            start=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2026, 6, 15, tzinfo=datetime.timezone.utc),
        )
        # email-then-day-then-model ordering.
        assert rows == [
            {
                "email": "alice@example.com",
                "model": "model-a",
                "day": "2026-06-01",
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 5,
                "cost_cents": 1.0,
            },
            {
                "email": "alice@example.com",
                "model": "model-b",
                "day": "2026-06-01",
                "input_tokens": 200,
                "output_tokens": 60,
                "cache_read_tokens": 0,
                "cost_cents": 2.0,
            },
            {
                "email": "alice@example.com",
                "model": "model-a",
                "day": "2026-06-08",
                "input_tokens": 300,
                "output_tokens": 70,
                "cache_read_tokens": 0,
                "cost_cents": 3.0,
            },
            {
                "email": "bob@example.com",
                "model": "model-a",
                "day": "2026-06-08",
                "input_tokens": 400,
                "output_tokens": 80,
                "cache_read_tokens": 0,
                "cost_cents": 4.0,
            },
        ]

    def test_model_filter_narrows(self, db_session: Session) -> None:
        _seed_two_users(db_session)
        rows = get_usage_export(
            db_session,
            start=_W1,
            end=datetime.datetime(2026, 6, 15, tzinfo=datetime.timezone.utc),
            model="model-b",
        )
        assert len(rows) == 1
        assert rows[0]["model"] == "model-b"
        assert rows[0]["email"] == "alice@example.com"

    def test_date_range_bounds_half_open(self, db_session: Session) -> None:
        _seed_two_users(db_session)
        # [W1, W2) excludes everything in W2.
        rows = get_usage_export(db_session, start=_W1, end=_W2)
        days = {r["day"] for r in rows}
        assert days == {"2026-06-01"}


class TestExportEndpoint:
    def test_nested_per_user_with_totals(self, db_session: Session) -> None:
        _seed_two_users(db_session)
        client = TestClient(_make_app(db_session, _ADMIN))
        resp = client.get(
            "/admin/usage/export", params={"start": "2026-06-01", "end": "2026-06-14"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["start"] == "2026-06-01"
        assert body["end"] == "2026-06-14"

        users = {u["email"]: u for u in body["users"]}
        assert set(users) == {"alice@example.com", "bob@example.com"}

        alice = users["alice@example.com"]
        assert len(alice["records"]) == 3
        # Totals roll up all of alice's records.
        assert alice["totals"]["input_tokens"] == 600  # 100 + 200 + 300
        assert alice["totals"]["output_tokens"] == 180  # 50 + 60 + 70
        assert alice["totals"]["cache_read_tokens"] == 5
        assert alice["totals"]["cost_cents"] == pytest.approx(6.0)

        bob = users["bob@example.com"]
        assert len(bob["records"]) == 1
        assert bob["totals"]["input_tokens"] == 400

    def test_model_filter_endpoint(self, db_session: Session) -> None:
        _seed_two_users(db_session)
        client = TestClient(_make_app(db_session, _ADMIN))
        body = client.get(
            "/admin/usage/export",
            params={"start": "2026-06-01", "end": "2026-06-14", "model": "model-b"},
        ).json()
        assert len(body["users"]) == 1
        assert body["users"][0]["email"] == "alice@example.com"
        assert all(r["model"] == "model-b" for r in body["users"][0]["records"])

    def test_date_range_end_excludes_later_window(self, db_session: Session) -> None:
        _seed_two_users(db_session)
        client = TestClient(_make_app(db_session, _ADMIN))
        # end=2026-06-07 -> half-open through 06-08 00:00, so W2 (06-08) excluded.
        body = client.get(
            "/admin/usage/export", params={"start": "2026-06-01", "end": "2026-06-07"}
        ).json()
        all_days = {r["day"] for u in body["users"] for r in u["records"]}
        assert all_days == {"2026-06-01"}
        assert "bob@example.com" not in {u["email"] for u in body["users"]}

    def test_non_admin_rejected(self, db_session: Session) -> None:
        client = TestClient(_make_app(db_session, _NON_ADMIN))
        resp = client.get("/admin/usage/export")
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "INSUFFICIENT_PERMISSIONS"


class TestResetUsageEndpoint:
    """POST /admin/usage/reset — admin-only; 404 on unknown email; on success it
    clears the resolved user's usage."""

    def test_unknown_user_is_404(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import onyx.server.features.usage.api as api

        monkeypatch.setattr(api, "get_user_by_email", lambda _email, _db: None)
        client = TestClient(_make_app(db_session, _ADMIN))
        resp = client.post("/admin/usage/reset", json={"user_email": "nope@x.com"})
        assert resp.status_code == 404

    def test_resets_found_user(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import onyx.server.features.usage.api as api

        class _U:
            id = "00000000-0000-0000-0000-0000000000aa"

        seen: dict[str, str] = {}
        monkeypatch.setattr(api, "get_user_by_email", lambda _email, _db: _U())
        monkeypatch.setattr(
            api,
            "reset_user_usage",
            lambda _db, user_id: seen.update(user_id=user_id) or 1,
        )
        client = TestClient(_make_app(db_session, _ADMIN))
        resp = client.post("/admin/usage/reset", json={"user_email": "u@x.com"})
        assert resp.status_code == 200
        assert seen["user_id"] == str(_U.id)

    def test_non_admin_rejected(self, db_session: Session) -> None:
        client = TestClient(_make_app(db_session, _NON_ADMIN))
        resp = client.post("/admin/usage/reset", json={"user_email": "u@x.com"})
        assert resp.status_code == 403
