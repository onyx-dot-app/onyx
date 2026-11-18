import threading
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode
from uuid import UUID

import httpx
import pytest
import requests
from sqlalchemy import event
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationOAuthProviderMode,
)
from onyx.db.integration_connection import upsert_connection__no_commit
from onyx.db.models import (
    Integration,
    IntegrationConnection,
    IntegrationOAuthClient,
)
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.connections import ConnectionProblem, ResolvedConnection
from tests.external_dependency_unit.integration_helpers import delete_integrations

TOKEN_URL = "https://auth.example.test/token"
AUTHORIZE_URL = "https://auth.example.test/authorize"


@pytest.fixture(autouse=True)
def _tenant(tenant_context: None) -> None:  # noqa: ARG001
    return None


@pytest.fixture(autouse=True)
def _delete_new_integrations(db_session: Session) -> Generator[None, None, None]:
    """Deletes the integrations that the test saves through ``db_session``."""
    integration_ids: list[int] = []

    def collect(_session: Session, instance: object) -> None:
        if isinstance(instance, Integration):
            integration_ids.append(instance.id)

    event.listen(db_session, "pending_to_persistent", collect)
    try:
        yield
    finally:
        event.remove(db_session, "pending_to_persistent", collect)
        delete_integrations(db_session, integration_ids)


def new_oauth_client(
    provider_mode: IntegrationOAuthProviderMode,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    pkce: bool | None = None,
    registration: dict[str, Any] | None = None,
    scopes: list[str] | None = None,
) -> IntegrationOAuthClient:
    """An unsaved OAuth client for the ``oauth_client`` argument of the
    integration factories. A manual client gets test endpoints."""
    manual = provider_mode is IntegrationOAuthProviderMode.MANUAL
    return IntegrationOAuthClient(
        provider_mode=provider_mode,
        authorization_url=AUTHORIZE_URL if manual else None,
        token_url=TOKEN_URL if manual else None,
        client_id=client_id,
        client_secret=client_secret,
        pkce=pkce,
        registration=registration,
        scopes=scopes,
    )


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


def expect_resolved(
    result: ResolvedConnection | ConnectionProblem,
) -> ResolvedConnection:
    if not isinstance(result, ResolvedConnection):
        pytest.fail(f"expected a connection, got {result}")
    return result


def expect_problem(result: ResolvedConnection | ConnectionProblem) -> ConnectionProblem:
    if not isinstance(result, ConnectionProblem):
        pytest.fail(f"expected a problem, got {result}")
    return result


def token_response(body: dict[str, Any], status: int = 200) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


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
        # When set, each request waits for this event before it responds.
        self.release: threading.Event | None = None
        self.entered = threading.Event()
        # Send the body form-encoded, as some MCP servers do.
        self.form_encoded = False
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def send(self, request: httpx.Request, *, mcp: bool) -> httpx.Response:  # noqa: ARG002
        with self._lock:
            self.requests.append(request)
        self.entered.set()
        if self.release is not None and not self.release.wait(timeout=30):
            raise TimeoutError("the test did not release the token request")
        if self.form_encoded:
            return httpx.Response(
                self.status_code,
                content=urlencode(self.body).encode(),
                headers={"content-type": "application/x-www-form-urlencoded"},
                request=request,
            )
        return httpx.Response(self.status_code, json=self.body, request=request)


@pytest.fixture
def token_endpoint() -> Generator[FakeTokenEndpoint, None, None]:
    fake = FakeTokenEndpoint()
    with patch("onyx.integrations.connections._send_token_request", fake.send):
        yield fake
