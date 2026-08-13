"""Admin /admin/usage/export: grouping, filters, auth, and get_usage_export helper."""

import datetime
import sqlite3
from collections.abc import Generator
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Table, create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import UserUsage
from onyx.db.user_usage import UsageExportRow, get_usage_export
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.features.usage.api import admin_usage_router
from onyx.server.features.usage.models import ResetUsageResponse


@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "JSON"


class _StubUser:
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

    @event.listens_for(engine, "connect")
    def _register_timezone(dbapi_connection: object, _: object) -> None:
        cast(sqlite3.Connection, dbapi_connection).create_function(
            "timezone", 2, lambda _tz, value: value
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


def _seed_usage(
    db_session: Session,
    user_id: str,
    model: str,
    flow: str,
    provider: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cost_cents: float,
    window_start: datetime.datetime,
) -> None:
    db_session.add(
        UserUsage(
            user_id=user_id,
            window_start=window_start,
            model=model,
            flow=flow,
            provider=provider or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cost_cents=cost_cents,
        )
    )


def _seed_two_users(db_session: Session) -> tuple[str, str]:
    """alice: model-a in W1 + W2, model-b in W1.  bob: model-a in W2."""
    alice = _add_user(db_session, "alice@example.com")
    bob = _add_user(db_session, "bob@example.com")

    _seed_usage(db_session, alice, "model-a", "CHAT", "openai", 100, 50, 5, 1.0, _W1)
    _seed_usage(db_session, alice, "model-b", "CHAT", "openai", 200, 60, 0, 2.0, _W1)
    _seed_usage(db_session, alice, "model-a", "CHAT", "openai", 300, 70, 0, 3.0, _W2)
    _seed_usage(db_session, bob, "model-a", "CHAT", "anthropic", 400, 80, 0, 4.0, _W2)
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
        assert rows == [
            UsageExportRow(
                email="alice@example.com",
                model="model-a",
                flow="CHAT",
                provider="openai",
                incognito=False,
                day="2026-06-01",
                input_tokens=100,
                output_tokens=50,
                cache_read_tokens=5,
                cost_cents=1.0,
            ),
            UsageExportRow(
                email="alice@example.com",
                model="model-b",
                flow="CHAT",
                provider="openai",
                incognito=False,
                day="2026-06-01",
                input_tokens=200,
                output_tokens=60,
                cache_read_tokens=0,
                cost_cents=2.0,
            ),
            UsageExportRow(
                email="alice@example.com",
                model="model-a",
                flow="CHAT",
                provider="openai",
                incognito=False,
                day="2026-06-08",
                input_tokens=300,
                output_tokens=70,
                cache_read_tokens=0,
                cost_cents=3.0,
            ),
            UsageExportRow(
                email="bob@example.com",
                model="model-a",
                flow="CHAT",
                provider="anthropic",
                incognito=False,
                day="2026-06-08",
                input_tokens=400,
                output_tokens=80,
                cache_read_tokens=0,
                cost_cents=4.0,
            ),
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
        assert rows[0].model == "model-b"
        assert rows[0].email == "alice@example.com"

    def test_orders_rows_by_flow_and_provider(self, db_session: Session) -> None:
        user_id = _add_user(db_session, "alice@example.com")
        _seed_usage(
            db_session,
            user_id,
            "model-a",
            "CHAT",
            "openai",
            100,
            50,
            0,
            1.0,
            _W1,
        )
        _seed_usage(
            db_session,
            user_id,
            "model-a",
            "BATCH",
            "anthropic",
            200,
            60,
            0,
            2.0,
            _W1,
        )
        db_session.commit()

        rows = get_usage_export(db_session, start=_W1, end=_W2)

        assert [(row.flow, row.provider) for row in rows] == [
            ("BATCH", "anthropic"),
            ("CHAT", "openai"),
        ]

    def test_date_range_bounds_half_open(self, db_session: Session) -> None:
        _seed_two_users(db_session)
        # [W1, W2) excludes everything in W2.
        rows = get_usage_export(db_session, start=_W1, end=_W2)
        days = {r.day for r in rows}
        assert days == {"2026-06-01"}


class TestExportEndpoint:
    def test_default_range_covers_thirty_calendar_days(
        self, db_session: Session
    ) -> None:
        client = TestClient(_make_app(db_session, _ADMIN))

        body = client.get("/admin/usage/export").json()

        start = datetime.date.fromisoformat(body["start"])
        end = datetime.date.fromisoformat(body["end"])
        # Inclusive endpoints differ by 29 days when the range has 30 dates.
        assert (end - start).days == 29

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
        alice, _ = _seed_two_users(db_session)
        _seed_usage(
            db_session,
            alice,
            "model-a",
            "CHAT",
            "openai",
            500,
            90,
            0,
            5.0,
            datetime.datetime(2026, 6, 7, tzinfo=datetime.timezone.utc),
        )
        db_session.commit()
        client = TestClient(_make_app(db_session, _ADMIN))
        # end=2026-06-07 -> half-open through 06-08 00:00, so W2 (06-08) excluded.
        body = client.get(
            "/admin/usage/export", params={"start": "2026-06-01", "end": "2026-06-07"}
        ).json()
        all_days = {r["day"] for u in body["users"] for r in u["records"]}
        assert all_days == {"2026-06-01", "2026-06-07"}
        assert "bob@example.com" not in {u["email"] for u in body["users"]}

    def test_non_admin_rejected(self, db_session: Session) -> None:
        client = TestClient(_make_app(db_session, _NON_ADMIN))
        resp = client.get("/admin/usage/export")
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "INSUFFICIENT_PERMISSIONS"

    def test_start_after_end_rejected(self, db_session: Session) -> None:
        client = TestClient(_make_app(db_session, _ADMIN))
        resp = client.get(
            "/admin/usage/export",
            params={"start": "2026-06-14", "end": "2026-06-01"},
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_INPUT"


class TestResetUsageEndpoint:
    def test_empty_email_is_rejected(self, db_session: Session) -> None:
        client = TestClient(_make_app(db_session, _ADMIN))
        resp = client.post("/admin/usage/reset", json={"user_email": ""})
        assert resp.status_code == 422

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

        window_start = datetime.datetime(2026, 7, 22, tzinfo=datetime.timezone.utc)
        seen: dict[str, object] = {}
        monkeypatch.setattr(api, "get_user_by_email", lambda _email, _db: _U())
        monkeypatch.setattr(
            api, "fetch_all_user_token_rate_limits", lambda *_a, **_k: []
        )
        monkeypatch.setattr(
            api, "fetch_all_global_token_rate_limits", lambda *_a, **_k: []
        )
        monkeypatch.setattr(
            api, "fetch_user_group_token_rate_limits", lambda *_a, **_k: {}
        )
        monkeypatch.setattr(
            api, "get_usage_reset_window_start", lambda _now, _limits: window_start
        )
        monkeypatch.setattr(
            api,
            "reset_user_usage",
            lambda _db, user_id, cutoff: (
                seen.update(user_id=user_id, cutoff=cutoff) or 1
            ),
        )
        client = TestClient(_make_app(db_session, _ADMIN))
        resp = client.post("/admin/usage/reset", json={"user_email": "u@x.com"})
        assert resp.status_code == 200
        assert resp.json() == {"reset_rows": 1}
        assert seen["user_id"] == str(_U.id)
        assert seen["cutoff"] == window_start

    def test_non_admin_rejected(self, db_session: Session) -> None:
        client = TestClient(_make_app(db_session, _NON_ADMIN))
        resp = client.post("/admin/usage/reset", json={"user_email": "u@x.com"})
        assert resp.status_code == 403

    def test_negative_reset_count_is_invalid(self) -> None:
        with pytest.raises(ValidationError):
            ResetUsageResponse(reset_rows=-1)
