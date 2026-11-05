from collections.abc import Generator
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AccountType, Permission
from onyx.db.models import TeamsBotConfig, User
from onyx.db.teams_bot import get_teams_bot_config
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.manage.teams_bot import api

PATH = "/manage/admin/teams-bot/config"
SECRET = "test-teams-credential"
PERSONA_ID = 41
UPDATED_PERSONA_ID = 42
CREATE = {
    "app_id": "11111111-1111-4111-8111-11111111111a",
    "directory_id": "22222222-2222-4222-8222-22222222222b",
    "client_secret": SECRET,
}


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
    persona_table = Table(
        "persona", MetaData(), Column("id", Integer, primary_key=True)
    )
    persona_table.create(engine)
    cast(Table, TeamsBotConfig.__table__).create(engine)
    with engine.begin() as connection:
        connection.execute(
            persona_table.insert(),
            [{"id": PERSONA_ID}, {"id": UPDATED_PERSONA_ID}],
        )
    try:
        with Session(engine) as db_session:
            yield db_session
    finally:
        engine.dispose()


@pytest.fixture
def client(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(api, "ENABLE_TEAMS_BOT", True)
    monkeypatch.setattr(api, "MULTI_TENANT", False)
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(api.router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[current_user] = lambda: User(
        id=uuid4(),
        account_type=AccountType.STANDARD,
        effective_permissions=[Permission.MANAGE_BOTS.value],
    )
    with TestClient(app) as test_client:
        yield test_client


def test_config_lifecycle_hides_and_preserves_secret(
    client: TestClient, session: Session
) -> None:
    assert client.get(PATH).json() is None
    created = client.post(PATH, json=CREATE)
    assert created.status_code == 200
    assert created.json() == {
        "app_id": CREATE["app_id"],
        "directory_id": CREATE["directory_id"],
        "enabled": False,
        "persona_id": None,
    }
    assert SECRET not in created.text
    assert "client_secret" not in client.get(PATH).json()
    updated = client.put(PATH, json={"enabled": True, "persona_id": None})
    assert updated.status_code == 200
    session.expire_all()
    config = get_teams_bot_config(session)
    assert config is not None and config.enabled
    assert config.client_secret.get_value(apply_mask=False) == SECRET
    rotated = client.put(
        PATH,
        json={
            "enabled": False,
            "persona_id": None,
            "client_secret": "replacement-credential",
        },
    )
    assert rotated.status_code == 200
    assert "replacement-credential" not in rotated.text
    session.expire_all()
    assert config.client_secret.get_value(apply_mask=False) == "replacement-credential"
    assert client.delete(PATH).status_code == 200
    assert client.get(PATH).json() is None


def test_duplicate_and_missing_config(client: TestClient) -> None:
    assert (
        client.put(PATH, json={"enabled": False, "persona_id": None}).status_code == 404
    )
    assert client.delete(PATH).status_code == 404
    assert client.post(PATH, json=CREATE).status_code == 200
    assert client.post(PATH, json=CREATE).status_code == 409
    assert client.get(PATH).json()["app_id"] == CREATE["app_id"]


@pytest.mark.parametrize("method", ["get", "post", "put", "delete"])
def test_requires_manage_bots(client: TestClient, method: str) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[current_user] = lambda: User(
        id=uuid4(),
        account_type=AccountType.STANDARD,
        effective_permissions=[Permission.BASIC_ACCESS.value],
    )
    response = client.request(method, PATH, json=CREATE)
    assert response.status_code == 403


@pytest.mark.parametrize(
    "enabled,multi_tenant,status", [(False, False, 404), (True, True, 403)]
)
@pytest.mark.parametrize("method", ["get", "post", "put", "delete"])
def test_deployment_gates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    multi_tenant: bool,
    status: int,
    method: str,
) -> None:
    monkeypatch.setattr(api, "ENABLE_TEAMS_BOT", enabled)
    monkeypatch.setattr(api, "MULTI_TENANT", multi_tenant)
    assert client.request(method, PATH, json=CREATE).status_code == status


@pytest.mark.parametrize("secret", ["", " ", "••••••••••••", "abcd...wxyz", "x" * 4097])
def test_rejects_invalid_secrets(client: TestClient, secret: str) -> None:
    assert (
        client.post(PATH, json={**CREATE, "client_secret": secret}).status_code == 422
    )
    assert client.get(PATH).json() is None


def test_identity_cannot_change_during_rotation(client: TestClient) -> None:
    assert client.post(PATH, json=CREATE).status_code == 200
    assert (
        client.put(
            PATH,
            json={"enabled": True, "persona_id": None, "directory_id": str(uuid4())},
        ).status_code
        == 422
    )
    assert client.get(PATH).json()["directory_id"] == CREATE["directory_id"]


def test_persona_access_checked_before_save(client: TestClient) -> None:
    with patch.object(api, "get_persona_by_id", side_effect=ValueError("Unavailable")):
        assert client.post(PATH, json={**CREATE, "persona_id": 99}).status_code == 404
    assert client.get(PATH).json() is None


def test_persona_id_round_trip(client: TestClient, session: Session) -> None:
    with patch.object(api, "get_persona_by_id"):
        created = client.post(PATH, json={**CREATE, "persona_id": PERSONA_ID})
        assert created.status_code == 200
        assert created.json()["persona_id"] == PERSONA_ID
        assert client.get(PATH).json()["persona_id"] == PERSONA_ID

        updated = client.put(
            PATH,
            json={"enabled": False, "persona_id": UPDATED_PERSONA_ID},
        )
        assert updated.status_code == 200
        assert updated.json()["persona_id"] == UPDATED_PERSONA_ID

    session.expire_all()
    config = get_teams_bot_config(session)
    assert config is not None
    assert config.persona_id == UPDATED_PERSONA_ID
    assert client.get(PATH).json()["persona_id"] == UPDATED_PERSONA_ID


@pytest.mark.usefixtures("enable_ee")
def test_enterprise_encrypts_secret(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ee.onyx.utils.encryption.ENCRYPTION_KEY_SECRET",
        "teams-test-key-0123456789abcdef012",
    )
    assert client.post(PATH, json=CREATE).status_code == 200
    stored = session.execute(
        text("SELECT client_secret FROM teams_bot_config")
    ).scalar_one()
    assert stored != SECRET.encode()
    session.expire_all()
    config = get_teams_bot_config(session)
    assert config is not None
    assert config.client_secret.get_value(apply_mask=False) == SECRET


@pytest.mark.parametrize(
    "field,value",
    [("app_id", "invalid"), ("directory_id", "invalid"), ("persona_id", -1)],
)
def test_rejects_invalid_identifiers(
    client: TestClient, field: str, value: str | int
) -> None:
    assert client.post(PATH, json={**CREATE, field: value}).status_code == 422
    assert client.get(PATH).json() is None
