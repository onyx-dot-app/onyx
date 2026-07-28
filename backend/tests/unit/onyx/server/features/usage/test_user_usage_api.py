"""Self-service /user/usage: isolation, aggregation, budget, model price."""

import datetime
import sqlite3
from collections.abc import Generator
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import (
    ModelCostOverride,
    TokenRateLimit,
    TokenRateLimit__UserGroup,
    User__UserGroup,
    UserUsage,
)
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.llm import cost_overrides
from onyx.llm.cost import get_model_price_per_million
from onyx.server.features.usage.api import user_usage_router


@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "JSON"


class _StubUser:
    def __init__(self, user_id: str) -> None:
        self.id = user_id


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

    for model in (
        UserUsage,
        ModelCostOverride,
        TokenRateLimit,
        User__UserGroup,
        TokenRateLimit__UserGroup,
    ):
        cast(Table, model.__table__).create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_app(db_session: Session, user: _StubUser) -> FastAPI:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(user_usage_router)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[current_user] = lambda: user
    return app


@pytest.fixture(autouse=True)
def _no_configured_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid querying LLM-provider tables absent from the SQLite test DB."""
    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_existing_llm_providers",
        lambda *_a, **_k: [],
    )


class _StubProvider:
    def __init__(self, provider: str | None) -> None:
        self.provider = provider


class _StubModelConfig:
    def __init__(self, name: str, provider: str | None) -> None:
        self.name = name
        self.llm_provider = _StubProvider(provider)


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
    db_session.flush()


class _StubMC:
    def __init__(self, name: str) -> None:
        self.name = name


class _StubProviderWithModels:
    def __init__(self, provider: str | None, model_names: list[str]) -> None:
        self.provider = provider
        self.model_configurations = [_StubMC(n) for n in model_names]


def _seed_current_window(db_session: Session, user_id: str) -> datetime.datetime:
    from onyx.db.user_usage import USER_USAGE_BUCKET_SECONDS
    from onyx.utils.datetime import get_window_start

    now = datetime.datetime.now(datetime.timezone.utc)
    window = get_window_start(now, USER_USAGE_BUCKET_SECONDS)
    _seed_usage(
        db_session, user_id, "gpt-4o", "CHAT", "openai", 100, 50, 0, 1.25, window
    )
    return window


def test_returns_only_callers_rows_and_aggregates(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = str(uuid4())
    other = str(uuid4())
    window = _seed_current_window(db_session, caller)
    # Same window, distinct model -> second per-day row for the caller.
    _seed_usage(
        db_session, caller, "claude-3", "CHAT", "anthropic", 200, 60, 5, 2.0, window
    )
    # Another user's usage must never surface.
    _seed_usage(
        db_session, other, "gpt-4o", "CHAT", "openai", 999, 999, 0, 99.0, window
    )

    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_default_llm_model", lambda _db: None
    )
    client = TestClient(_make_app(db_session, _StubUser(caller)))
    resp = client.get("/user/usage")
    assert resp.status_code == 200
    body = resp.json()

    models = {r["model"]: r for r in body["per_day_by_model"]}
    assert set(models) == {"gpt-4o", "claude-3"}
    assert models["gpt-4o"]["input_tokens"] == 100
    assert models["claude-3"]["output_tokens"] == 60
    assert models["claude-3"]["cache_read_tokens"] == 5
    # No row leaks the other user's 999s.
    assert all(r["input_tokens"] != 999 for r in body["per_day_by_model"])

    assert body["window_cost_cents"] == pytest.approx(3.25)  # 1.25 + 2.0
    assert body["budget_cents"] is None
    assert body["budget_remaining_cents"] is None
    assert body["selected_model_price"] is None


def test_selected_model_price_known_model(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = str(uuid4())
    _seed_current_window(db_session, caller)
    monkeypatch.setattr(cost_overrides, "get_current_tenant_id", lambda: "public")
    cost_overrides.invalidate_override_cache()  # no override; price from litellm
    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_default_llm_model",
        lambda _db: _StubModelConfig("gpt-4o", "openai"),
    )

    client = TestClient(_make_app(db_session, _StubUser(caller)))
    price = client.get("/user/usage").json()["selected_model_price"]
    assert price["model"] == "gpt-4o"
    assert price["provider"] == "openai"
    # litellm prices gpt-4o at $2.50 in / $10.00 out per 1M.
    assert price["input_per_mtok"] == pytest.approx(2.5)
    assert price["output_per_mtok"] == pytest.approx(10.0)


def test_selected_model_price_unknown_model_nulls(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = str(uuid4())
    _seed_current_window(db_session, caller)
    monkeypatch.setattr(cost_overrides, "get_current_tenant_id", lambda: "public")
    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_default_llm_model",
        lambda _db: _StubModelConfig("totally-unknown-model-xyz", None),
    )

    client = TestClient(_make_app(db_session, _StubUser(caller)))
    price = client.get("/user/usage").json()["selected_model_price"]
    assert price is None


class TestGetModelPricePerMillion:
    def test_override_beats_litellm(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cost_overrides, "get_current_tenant_id", lambda: "public")
        cost_overrides.upsert_override(db_session, "gpt-4o", 1.0, 4.0)
        cost_overrides.invalidate_override_cache()

        in_price, out_price = get_model_price_per_million(
            "gpt-4o", "openai", db_session
        )
        assert in_price == pytest.approx(1.0)
        assert out_price == pytest.approx(4.0)

    def test_litellm_fallback_when_no_override(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cost_overrides, "get_current_tenant_id", lambda: "public")
        # Clear tenant override cache between tests.
        cost_overrides.invalidate_override_cache()
        in_price, out_price = get_model_price_per_million(
            "gpt-4o", "openai", db_session
        )
        assert in_price == pytest.approx(2.5)
        assert out_price == pytest.approx(10.0)

    def test_unknown_model_nulls(self) -> None:
        assert get_model_price_per_million("totally-unknown-model-xyz", None) == (
            None,
            None,
        )

    def test_never_raises_on_lookup_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_a: object, **_k: object) -> None:
            raise RuntimeError("litellm exploded")

        import litellm

        monkeypatch.setattr(litellm, "get_model_info", _boom)
        assert get_model_price_per_million("gpt-4o", "openai") == (None, None)


def test_budget_reflects_user_cost_limit(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.db.models import TokenRateLimitScope

    caller = str(uuid4())
    _seed_current_window(db_session, caller)  # records 1.25c of cost
    db_session.add(
        TokenRateLimit(
            enabled=True,
            token_budget=None,
            cost_budget_cents=100.0,
            period_hours=168,
            scope=TokenRateLimitScope.USER,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_default_llm_model", lambda _db: None
    )

    body = (
        TestClient(_make_app(db_session, _StubUser(caller))).get("/user/usage").json()
    )
    assert body["budget_cents"] == pytest.approx(100.0)
    assert body["budget_remaining_cents"] == pytest.approx(98.75)  # 100 - 1.25


def test_budget_reflects_global_cost_limit(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.db.models import TokenRateLimitScope

    caller = str(uuid4())
    other = str(uuid4())
    window = _seed_current_window(db_session, caller)  # caller records 1.25c
    # A GLOBAL budget sums tenant-wide cost, so another user's spend in the same
    # window must count against the caller's remaining headroom too.
    _seed_usage(db_session, other, "gpt-4o", "CHAT", "openai", 500, 100, 0, 5.0, window)
    db_session.add(
        TokenRateLimit(
            enabled=True,
            token_budget=None,
            cost_budget_cents=100.0,
            period_hours=168,
            scope=TokenRateLimitScope.GLOBAL,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_default_llm_model", lambda _db: None
    )

    body = (
        TestClient(_make_app(db_session, _StubUser(caller))).get("/user/usage").json()
    )
    assert body["budget_cents"] == pytest.approx(100.0)
    # Includes both users' spend because this is a global limit.
    assert body["budget_remaining_cents"] == pytest.approx(93.75)


def test_available_model_prices_lists_priced_models(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = str(uuid4())
    _seed_current_window(db_session, caller)
    monkeypatch.setattr(cost_overrides, "get_current_tenant_id", lambda: "public")
    cost_overrides.invalidate_override_cache()
    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_default_llm_model", lambda _db: None
    )
    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_existing_llm_providers",
        lambda *_a, **_k: [
            _StubProviderWithModels("openai", ["gpt-4o", "totally-unknown-model-xyz"])
        ],
    )

    body = (
        TestClient(_make_app(db_session, _StubUser(caller))).get("/user/usage").json()
    )
    prices = {p["model"]: p for p in body["available_model_prices"]}
    assert prices["gpt-4o"]["input_per_mtok"] == pytest.approx(2.5)
    assert prices["gpt-4o"]["output_per_mtok"] == pytest.approx(10.0)
    assert "cache_per_mtok" in prices["gpt-4o"]
    # An unpriced model is skipped, not surfaced with null prices.
    assert "totally-unknown-model-xyz" not in prices


def test_budget_reflects_group_cost_limit(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.db.models import TokenRateLimitScope

    caller = str(uuid4())
    _seed_current_window(db_session, caller)  # records 1.25c of cost
    limit = TokenRateLimit(
        enabled=True,
        token_budget=None,
        cost_budget_cents=100.0,
        period_hours=168,
        scope=TokenRateLimitScope.USER_GROUP,
    )
    db_session.add(limit)
    db_session.flush()
    db_session.add(User__UserGroup(user_id=caller, user_group_id=1))
    db_session.add(TokenRateLimit__UserGroup(rate_limit_id=limit.id, user_group_id=1))
    db_session.commit()
    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_default_llm_model", lambda _db: None
    )

    body = (
        TestClient(_make_app(db_session, _StubUser(caller))).get("/user/usage").json()
    )
    assert body["budget_cents"] == pytest.approx(100.0)
    assert body["budget_remaining_cents"] == pytest.approx(98.75)  # 100 - 1.25
