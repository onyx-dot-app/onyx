"""Signed HTTP deliveries use real storage; only transport dispatch is controlled."""

import hashlib
import hmac
import json
from collections.abc import Generator
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import inspect, select, text, update
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.marketplace_webhook import receive_marketplace_webhook__no_commit
from onyx.db.models import Marketplace
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.webhook_server import marketplace as receiver
from onyx.webhook_server.api import create_webhook_app
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant

SECRET = "test-marketplace-hook-secret"
PUSH = {"repository": {"full_name": "acme/tools"}, "ref": "refs/heads/main"}
pytestmark = pytest.mark.usefixtures("tenant", "dispatch")


@pytest.fixture
def hook(session: Session, marketplace: Marketplace) -> Marketplace:
    session.execute(
        update(Marketplace)
        .where(Marketplace.id == marketplace.id)
        .values(webhook_secret=SECRET, webhook_ref="refs/heads/main", webhook_id="123")
    )
    session.commit()
    session.refresh(marketplace)
    return marketplace


@pytest.fixture
def dispatch() -> Generator[Mock, None, None]:
    with patch.object(receiver, "dispatch_marketplace_sync") as send:
        yield send


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with (
        patch.object(receiver, "MULTI_TENANT", False),
        patch(
            "onyx.webhook_server.api.create_prometheus_instrumentator",
            return_value=Instrumentator(registry=CollectorRegistry()),
        ),
    ):
        with TestClient(create_webhook_app()) as client:
            yield client


def signed_headers(body: bytes, event: str = "push") -> dict[str, str]:
    return {
        "x-hub-signature-256": "sha256="
        + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
        "x-github-event": event,
        "x-github-hook-id": "123",
        "content-type": "application/json",
    }


def url(identifier: UUID) -> str:
    return f"/marketplaces/{identifier}/github"


def test_push_commits_before_dispatch(
    client: TestClient, hook: Marketplace, dispatch: Mock, tenant: str
) -> None:
    def observe(tenant_id: str, identifier: UUID) -> None:
        assert tenant_id == tenant and identifier == hook.id
        with get_session_with_current_tenant() as observer:
            saved = observer.get(Marketplace, identifier)
            assert saved is not None and saved.sync_requested
            assert saved.webhook_last_delivery_at is not None

    dispatch.side_effect = observe
    body = json.dumps(PUSH).encode()
    response = client.post(url(hook.id), content=body, headers=signed_headers(body))
    assert response.status_code == 200, response.text
    assert response.json() == {"queued": True}
    dispatch.assert_called_once_with(tenant, hook.id)


@pytest.mark.parametrize("case", ["ping", "other_branch", "other_tag", "other_event"])
def test_valid_unrelated_delivery_does_not_request_sync(
    client: TestClient, session: Session, hook: Marketplace, dispatch: Mock, case: str
) -> None:
    payload = dict(PUSH)
    if case == "other_branch":
        payload["ref"] = "refs/heads/other"
    elif case == "other_tag":
        payload["ref"] = "refs/tags/main"
    body = json.dumps(payload).encode()
    event = "ping" if case == "ping" else "issues" if case == "other_event" else "push"
    response = client.post(
        url(hook.id), content=body, headers=signed_headers(body, event)
    )
    assert response.status_code == 200 and response.json() == {"queued": False}
    session.refresh(hook)
    assert not hook.sync_requested
    assert (hook.webhook_last_delivery_at is not None) == (case != "other_event")
    dispatch.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        "missing_signature",
        "bad_signature",
        "wrong_hook",
        "wrong_repository",
        "bad_json",
        "missing_ref",
    ],
)
def test_rejected_delivery_writes_nothing(
    client: TestClient, session: Session, hook: Marketplace, dispatch: Mock, case: str
) -> None:
    payload = dict(PUSH)
    if case == "wrong_repository":
        payload["repository"] = {"full_name": "acme/other"}
    elif case == "missing_ref":
        payload.pop("ref")
    body = b"{" if case == "bad_json" else json.dumps(payload).encode()
    headers = signed_headers(body)
    if case == "missing_signature":
        headers.pop("x-hub-signature-256")
    elif case == "bad_signature":
        headers["x-hub-signature-256"] = "sha256=not-a-signature"
    elif case == "wrong_hook":
        headers["x-github-hook-id"] = "456"
    response = client.post(url(hook.id), content=body, headers=headers)
    assert response.status_code == (
        401 if case in {"missing_signature", "bad_signature", "wrong_hook"} else 400
    )
    session.refresh(hook)
    assert not hook.sync_requested and hook.webhook_last_delivery_at is None
    dispatch.assert_not_called()


def test_bad_signature_does_not_wait_for_marketplace_lock(
    session: Session, hook: Marketplace
) -> None:
    session.scalar(
        select(Marketplace).where(Marketplace.id == hook.id).with_for_update()
    )
    with get_session_with_current_tenant() as delivery:
        delivery.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OnyxError) as error:
            receive_marketplace_webhook__no_commit(
                hook.id,
                json.dumps(PUSH).encode(),
                signature="sha256=invalid",
                event="push",
                hook_id="123",
                db_session=delivery,
            )
        assert error.value.error_code == OnyxErrorCode.UNAUTHENTICATED


def test_dispatch_failure_keeps_durable_request(
    client: TestClient, session: Session, hook: Marketplace, dispatch: Mock
) -> None:
    dispatch.side_effect = RuntimeError("broker unavailable")
    body = json.dumps(PUSH).encode()
    response = client.post(url(hook.id), content=body, headers=signed_headers(body))
    assert response.status_code == 200 and response.json() == {"queued": True}
    session.refresh(hook)
    assert hook.sync_requested and hook.webhook_last_delivery_at is not None


@pytest.mark.parametrize("case", ["cloud", "missing", "unregistered", "oversized"])
def test_receiver_boundaries(
    client: TestClient, session: Session, hook: Marketplace, dispatch: Mock, case: str
) -> None:
    body = json.dumps(PUSH).encode()
    identifier = hook.id
    if case == "unregistered":
        hook.webhook_secret = None
        session.commit()
    elif case == "missing":
        identifier = uuid4()
    elif case == "oversized":
        body = b"x" * (5 * 1024 * 1024 + 1)
    with patch.object(receiver, "MULTI_TENANT", case == "cloud"):
        response = client.post(
            url(identifier), content=body, headers=signed_headers(body)
        )
    assert response.status_code == (400 if case == "oversized" else 404)
    session.refresh(hook)
    assert not hook.sync_requested and hook.webhook_last_delivery_at is None
    dispatch.assert_not_called()


def test_webhook_migration_round_trip(
    session: Session, hook: Marketplace, tenant: str
) -> None:
    identifier, name = hook.id, hook.name
    config = Config("backend/alembic.ini")
    config.set_main_option("script_location", "backend/alembic")
    revision = ScriptDirectory.from_config(config).get_revision("8fc170c91f59")
    assert revision is not None
    connection = session.connection()
    connection.execute(
        text("SELECT set_config('search_path', :schema, true)"),
        {"schema": connection.dialect.identifier_preparer.quote_schema(tenant)},
    )
    with Operations.context(MigrationContext.configure(connection)):
        revision.module.downgrade()
        columns = {
            column["name"] for column in inspect(connection).get_columns("marketplace")
        }
        assert (
            "webhook_ref" not in columns and "webhook_last_delivery_at" not in columns
        )
        assert (
            connection.scalar(
                text("SELECT name FROM marketplace WHERE id = :id"), {"id": identifier}
            )
            == name
        )
        revision.module.upgrade()
    session.expire_all()
    saved = session.get(Marketplace, identifier)
    assert saved is not None and saved.name == name
    assert saved.webhook_ref is None and saved.webhook_last_delivery_at is None
    assert saved.webhook_id == "123" and saved.webhook_secret is not None
