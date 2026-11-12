"""Cost-override CRUD, auth, and cache invalidation.

Gated on MANAGE_LLMS: negotiated rates are part of configuring language models,
not a separate admin surface.
"""

import sqlite3
from collections.abc import Generator
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine, delete, event
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from onyx.auth.users import current_user
from onyx.db.cost_override import (
    create_cost_override,
    delete_cost_override,
    fetch_cost_override,
    fetch_cost_overrides,
    update_cost_override,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AccountType, Permission
from onyx.db.models import (
    LLMProvider,
    ModelConfiguration,
    ModelCostOverride,
    VoiceProvider,
)
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.features.usage.api import router as cost_override_router

_BASE = "/admin/cost-overrides"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "JSON"


class _StubUser:
    """Minimal stand-in for User, carrying only what require_permission reads."""

    def __init__(self, permissions: list[str]) -> None:
        self.id = "00000000-0000-0000-0000-000000000001"
        self.effective_permissions = permissions
        self.account_type = AccountType.STANDARD
        self.is_group_manager = False


_ADMIN = _StubUser([Permission.FULL_ADMIN_PANEL_ACCESS.value])
_LLM_MANAGER = _StubUser([Permission.MANAGE_LLMS.value])
_OTHER_HOLDER = _StubUser([Permission.MANAGE_AGENTS.value])
_NON_ADMIN = _StubUser([])


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    # StaticPool: one in-memory DB survives endpoint commit().
    engine: Engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    # SQLite enforces foreign keys (and ON DELETE CASCADE) only when asked.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cast(sqlite3.Connection, dbapi_connection).execute("PRAGMA foreign_keys=ON")

    # voice_provider only because llm_provider references it; with foreign
    # keys on, SQLite needs every referenced table to exist.
    for model in (VoiceProvider, LLMProvider, ModelConfiguration, ModelCostOverride):
        cast(Table, model.__table__).create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed_config(
    db_session: Session,
    model: str = "gpt-6-sol",
    display_name: str | None = None,
    provider_name: str | None = "Team OpenAI",
) -> int:
    llm_provider = LLMProvider(name=provider_name, provider="openai")
    db_session.add(llm_provider)
    db_session.flush()
    config = ModelConfiguration(
        llm_provider_id=llm_provider.id,
        name=model,
        display_name=display_name,
        is_visible=True,
    )
    db_session.add(config)
    db_session.commit()
    return config.id


def _rates(input_rate: float = 2.5, output_rate: float = 10.0) -> dict[str, Any]:
    return {"input_cost_per_mtok": input_rate, "output_cost_per_mtok": output_rate}


def _make_app(db_session: Session, user: _StubUser) -> FastAPI:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(cost_override_router)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[current_user] = lambda: user
    return app


def test_create_then_update_and_list(db_session: Session) -> None:
    config_id = _seed_config(db_session, display_name="GPT-4o")
    client = TestClient(_make_app(db_session, _ADMIN))

    create = client.post(
        _BASE, json={"model_configuration_id": config_id, **_rates(2.5, 10.0)}
    )
    assert create.status_code == 200, create.text
    assert create.json()["input_cost_per_mtok"] == 2.5

    update = client.put(f"{_BASE}/{config_id}", json=_rates(1.0, 4.0))
    assert update.status_code == 200, update.text
    assert update.json()["output_cost_per_mtok"] == 4.0

    listing = client.get(_BASE)
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["model_configuration_id"] == config_id
    assert row["model_name"] == "gpt-6-sol"
    assert row["model_display_name"] == "GPT-4o"
    assert row["llm_provider_name"] == "Team OpenAI"
    assert row["provider"] == "openai"
    assert isinstance(row["llm_provider_id"], int)
    assert row["input_cost_per_mtok"] == 1.0


def test_list_display_name_falls_back_to_model_name(db_session: Session) -> None:
    config_id = _seed_config(db_session, model="custom-model", provider_name=None)
    client = TestClient(_make_app(db_session, _ADMIN))
    client.post(_BASE, json={"model_configuration_id": config_id, **_rates()})

    row = client.get(_BASE).json()[0]
    assert row["model_display_name"] == "custom-model"
    assert row["llm_provider_name"] is None


def test_duplicate_create_conflicts(db_session: Session) -> None:
    config_id = _seed_config(db_session)
    client = TestClient(_make_app(db_session, _ADMIN))
    body = {"model_configuration_id": config_id, **_rates()}
    assert client.post(_BASE, json=body).status_code == 200

    again = client.post(_BASE, json=body)
    assert again.status_code == 409
    assert again.json()["error_code"] == "CONFLICT"


def test_racing_create_conflicts_instead_of_500(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent create can win the unique key after the pre-check."""
    config_id = _seed_config(db_session)
    client = TestClient(_make_app(db_session, _ADMIN))
    body = {"model_configuration_id": config_id, **_rates()}
    assert client.post(_BASE, json=body).status_code == 200

    # The pre-check misses the existing row, as it would mid-race.
    monkeypatch.setattr(
        "onyx.server.features.usage.api.fetch_cost_override",
        lambda _session, _model_configuration_id: None,
    )
    again = client.post(_BASE, json=body)
    assert again.status_code == 409
    assert again.json()["error_code"] == "CONFLICT"


def test_create_for_missing_configuration_404s(db_session: Session) -> None:
    client = TestClient(_make_app(db_session, _ADMIN))
    resp = client.post(_BASE, json={"model_configuration_id": 999, **_rates()})
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"
    assert fetch_cost_overrides(db_session) == []


def test_update_without_override_404s(db_session: Session) -> None:
    config_id = _seed_config(db_session)
    client = TestClient(_make_app(db_session, _ADMIN))
    resp = client.put(f"{_BASE}/{config_id}", json=_rates())
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


def test_update_moves_override_to_another_model(db_session: Session) -> None:
    source = _seed_config(db_session, model="gpt-4o")
    target = _seed_config(db_session, model="gpt-4.1", provider_name="Team B")
    client = TestClient(_make_app(db_session, _ADMIN))
    assert (
        client.post(
            _BASE, json={"model_configuration_id": source, **_rates()}
        ).status_code
        == 200
    )

    moved = client.put(
        f"{_BASE}/{source}",
        json={"model_configuration_id": target, **_rates(3.0, 12.0)},
    )
    assert moved.status_code == 200
    body = moved.json()
    assert body["model_configuration_id"] == target
    assert body["model_name"] == "gpt-4.1"
    assert body["input_cost_per_mtok"] == 3.0

    listed = client.get(_BASE).json()
    assert [row["model_configuration_id"] for row in listed] == [target]


def test_update_to_the_same_model_keeps_it(db_session: Session) -> None:
    config_id = _seed_config(db_session)
    client = TestClient(_make_app(db_session, _ADMIN))
    client.post(_BASE, json={"model_configuration_id": config_id, **_rates()})

    resp = client.put(
        f"{_BASE}/{config_id}",
        json={"model_configuration_id": config_id, **_rates(4.0, 8.0)},
    )
    assert resp.status_code == 200
    assert resp.json()["model_configuration_id"] == config_id
    assert resp.json()["input_cost_per_mtok"] == 4.0


def test_move_to_missing_model_404s(db_session: Session) -> None:
    config_id = _seed_config(db_session)
    client = TestClient(_make_app(db_session, _ADMIN))
    client.post(_BASE, json={"model_configuration_id": config_id, **_rates()})

    resp = client.put(
        f"{_BASE}/{config_id}",
        json={"model_configuration_id": config_id + 999, **_rates()},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


def test_move_onto_a_model_with_an_override_conflicts(db_session: Session) -> None:
    source = _seed_config(db_session, model="gpt-4o")
    target = _seed_config(db_session, model="gpt-4.1", provider_name="Team B")
    client = TestClient(_make_app(db_session, _ADMIN))
    for config_id in (source, target):
        client.post(_BASE, json={"model_configuration_id": config_id, **_rates()})

    resp = client.put(
        f"{_BASE}/{source}",
        json={"model_configuration_id": target, **_rates(3.0, 12.0)},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONFLICT"
    # Neither override changed.
    rates = {
        row["model_configuration_id"]: row["input_cost_per_mtok"]
        for row in client.get(_BASE).json()
    }
    assert rates == {source: 2.5, target: 2.5}


def test_delete_removes_then_404(db_session: Session) -> None:
    config_id = _seed_config(db_session, model="claude-haiku-4-5")
    client = TestClient(_make_app(db_session, _ADMIN))
    client.post(_BASE, json={"model_configuration_id": config_id, **_rates(0.8, 4.0)})

    deleted = client.delete(f"{_BASE}/{config_id}")
    assert deleted.status_code == 200
    assert client.get(_BASE).json() == []

    missing = client.delete(f"{_BASE}/{config_id}")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "NOT_FOUND"


def test_deleting_model_configuration_removes_its_override(
    db_session: Session,
) -> None:
    config_id = _seed_config(db_session)
    create_cost_override(db_session, config_id, 2.5, 10.0)
    db_session.commit()

    db_session.execute(
        delete(ModelConfiguration).where(ModelConfiguration.id == config_id)
    )
    db_session.commit()

    assert fetch_cost_override(db_session, config_id) is None


@pytest.mark.parametrize("user", [_NON_ADMIN, _OTHER_HOLDER])
def test_callers_without_manage_llms_rejected(
    user: _StubUser, db_session: Session
) -> None:
    """_OTHER_HOLDER holds a different permission, so this pins MANAGE_LLMS
    specifically rather than "holds something"."""
    config_id = _seed_config(db_session)
    client = TestClient(_make_app(db_session, user))
    resp = client.post(_BASE, json={"model_configuration_id": config_id, **_rates()})
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "INSUFFICIENT_PERMISSIONS"


def test_manage_llms_holder_admitted(db_session: Session) -> None:
    """The admin tests all act as FULL_ADMIN_PANEL_ACCESS, which short-circuits
    every gate — only this one would fail if the routes reverted to admin-only."""
    config_id = _seed_config(db_session)
    client = TestClient(_make_app(db_session, _LLM_MANAGER))
    resp = client.post(_BASE, json={"model_configuration_id": config_id, **_rates()})
    assert resp.status_code == 200, resp.text
    assert client.get(_BASE).status_code == 200


def test_writes_invalidate_cache(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        "onyx.server.features.usage.api.invalidate_override_cache",
        lambda: calls.append(1),
    )
    config_id = _seed_config(db_session)
    client = TestClient(_make_app(db_session, _ADMIN))

    client.post(_BASE, json={"model_configuration_id": config_id, **_rates()})
    assert len(calls) == 1

    client.put(f"{_BASE}/{config_id}", json=_rates(1.0, 4.0))
    assert len(calls) == 2

    client.delete(f"{_BASE}/{config_id}")
    assert len(calls) == 3


def test_db_helpers_create_update_list_delete(db_session: Session) -> None:
    gpt_id = _seed_config(db_session, model="gpt-6-sol")
    claude_id = _seed_config(db_session, model="claude-haiku-4-5")

    create_cost_override(db_session, gpt_id, 2.5, 10.0)
    create_cost_override(db_session, claude_id, 0.8, 4.0)
    updated = update_cost_override(db_session, gpt_id, 1.0, 4.0)
    assert updated is not None
    assert update_cost_override(db_session, 999, 1.0, 4.0) is None

    rows = fetch_cost_overrides(db_session)
    # Ordered by model name.
    assert [r.model_configuration.name for r in rows] == [
        "claude-haiku-4-5",
        "gpt-6-sol",
    ]
    gpt = fetch_cost_override(db_session, gpt_id)
    assert gpt is not None
    assert gpt.input_cost_per_mtok == 1.0

    assert delete_cost_override(db_session, gpt_id) is True
    assert delete_cost_override(db_session, gpt_id) is False
    assert [r.model_configuration_id for r in fetch_cost_overrides(db_session)] == [
        claude_id
    ]


@pytest.mark.parametrize(
    ("method", "path_suffix"),
    [("post", ""), ("put", "/{id}")],
)
def test_negative_rate_rejected_by_api(
    method: str, path_suffix: str, db_session: Session
) -> None:
    config_id = _seed_config(db_session)
    create_cost_override(db_session, config_id, 2.5, 10.0)
    db_session.commit()
    client = TestClient(_make_app(db_session, _ADMIN))

    res = client.request(
        method,
        _BASE + path_suffix.format(id=config_id),
        json={"model_configuration_id": config_id, **_rates(-1.0, 4.0)},
    )
    assert res.status_code == 422
    row = fetch_cost_override(db_session, config_id)
    assert row is not None
    assert row.input_cost_per_mtok == 2.5


def test_db_helpers_reject_negative_rate(db_session: Session) -> None:
    config_id = _seed_config(db_session)
    with pytest.raises(ValueError):
        create_cost_override(db_session, config_id, -1.0, 4.0)
    create_cost_override(db_session, config_id, 2.5, 10.0)
    with pytest.raises(ValueError):
        update_cost_override(db_session, config_id, 1.0, 4.0, -0.5)
