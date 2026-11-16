import threading
import time
from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration_connection import upsert_connection__no_commit
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationConnection,
    IntegrationOAuthClient,
    MCPConnectionConfig,
    MCPServer,
    OAuthConfig,
    Tool,
)
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.connections import CREDENTIAL_IMPORT_DONE_KEY
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError

TOKEN_URL = "https://auth.example.test/token"
AUTHORIZE_URL = "https://auth.example.test/authorize"


@pytest.fixture(autouse=True)
def _tenant(tenant_context: None) -> None:  # noqa: ARG001
    return None


class MakeIntegration(Protocol):
    def __call__(
        self,
        *,
        auth_mode: IntegrationAuthMode,
        auth_method: IntegrationAuthMethod | None,
        kind: IntegrationKind = IntegrationKind.API,
        header_template: dict[str, str] | None = None,
        provider_mode: IntegrationOAuthProviderMode | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        pkce: bool | None = None,
        registration: dict[str, Any] | None = None,
        scopes: list[str] | None = None,
    ) -> Integration: ...


@pytest.fixture
def make_integration(db_session: Session) -> Generator[MakeIntegration, None, None]:
    created: list[int] = []

    def make(
        *,
        auth_mode: IntegrationAuthMode,
        auth_method: IntegrationAuthMethod | None,
        kind: IntegrationKind = IntegrationKind.API,
        header_template: dict[str, str] | None = None,
        provider_mode: IntegrationOAuthProviderMode | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        pkce: bool | None = None,
        registration: dict[str, Any] | None = None,
        scopes: list[str] | None = None,
    ) -> Integration:
        integration = Integration(
            kind=kind,
            name=f"Test integration {len(created)}",
            auth_mode=auth_mode,
            auth_method=auth_method,
            header_template=header_template,
        )
        db_session.add(integration)
        db_session.flush()
        if provider_mode is not None:
            db_session.add(
                IntegrationOAuthClient(
                    integration_id=integration.id,
                    provider_mode=provider_mode,
                    authorization_url=(
                        AUTHORIZE_URL
                        if provider_mode is IntegrationOAuthProviderMode.MANUAL
                        else None
                    ),
                    token_url=(
                        TOKEN_URL
                        if provider_mode is IntegrationOAuthProviderMode.MANUAL
                        else None
                    ),
                    client_id=client_id,
                    client_secret=client_secret,
                    pkce=pkce,
                    registration=registration,
                    scopes=scopes,
                )
            )
        db_session.commit()
        created.append(integration.id)
        return integration

    try:
        yield make
    finally:
        db_session.rollback()
        if created:
            db_session.execute(delete(Integration).where(Integration.id.in_(created)))
            db_session.commit()


def add_connection(
    db_session: Session,
    integration: Integration,
    user_id: UUID | None,
    secret: ConnectionSecret,
    *,
    expires_at: datetime | None = None,
) -> IntegrationConnection:
    connection = upsert_connection__no_commit(
        db_session,
        integration_id=integration.id,
        user_id=user_id,
        secret=secret.model_dump(mode="json"),
        expires_at=expires_at,
        granted_scopes=None,
    )
    db_session.commit()
    return connection


def expired() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=5)


def far_future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=1)


class FakeTokenEndpoint:
    """Stands in for the remote token endpoint of every refresh path that
    goes through ``_send_token_request``."""

    def __init__(self) -> None:
        self.status_code = 200
        self.body: dict[str, Any] = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        self.delay_s = 0.0
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def send(self, request: httpx.Request, *, mcp: bool) -> httpx.Response:  # noqa: ARG002
        with self._lock:
            self.requests.append(request)
        if self.delay_s:
            time.sleep(self.delay_s)
        return httpx.Response(self.status_code, json=self.body, request=request)


@pytest.fixture
def token_endpoint() -> Generator[FakeTokenEndpoint, None, None]:
    fake = FakeTokenEndpoint()
    with patch("onyx.integrations.connections._send_token_request", fake.send):
        yield fake


@pytest.fixture
def import_flag() -> Generator[Callable[[bool], None], None, None]:
    """Set the import done flag for one test and restore it after."""
    store = get_kv_store()
    try:
        original: Any = store.load(CREDENTIAL_IMPORT_DONE_KEY)
        had_value = True
    except KvKeyNotFoundError:
        original = None
        had_value = False

    def set_flag(done: bool) -> None:
        if done:
            store.store(CREDENTIAL_IMPORT_DONE_KEY, True)
            return
        try:
            store.delete(CREDENTIAL_IMPORT_DONE_KEY)
        except KvKeyNotFoundError:
            pass

    try:
        yield set_flag
    finally:
        if had_value:
            store.store(CREDENTIAL_IMPORT_DONE_KEY, original)
        else:
            set_flag(False)


@pytest.fixture
def legacy_rows(db_session: Session) -> Generator[list[object], None, None]:
    """Old credential rows a test makes; deleted after the test."""
    rows: list[object] = []
    try:
        yield rows
    finally:
        db_session.rollback()
        for row in reversed(rows):
            if isinstance(row, (MCPServer, Tool, OAuthConfig, ExternalApp)):
                model = type(row)
                db_session.execute(delete(model).where(model.id == row.id))
            elif isinstance(row, MCPConnectionConfig):
                db_session.execute(
                    delete(MCPConnectionConfig).where(MCPConnectionConfig.id == row.id)
                )
        db_session.commit()
