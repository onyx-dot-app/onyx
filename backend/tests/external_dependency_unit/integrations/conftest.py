import threading
import time
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
import pytest
import requests
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    IntegrationOAuthProviderMode,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.integration_connection import upsert_connection__no_commit
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationConnection,
    IntegrationOAuthClient,
    MCPServer,
)
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.connections import ConnectionProblem, ResolvedConnection

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
        app_type: ExternalAppType = ExternalAppType.CUSTOM,
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
    """An MCP integration gets an MCP server; an API integration gets an
    external app of ``app_type``."""
    server_ids: list[int] = []
    app_ids: list[int] = []

    def make(
        *,
        auth_mode: IntegrationAuthMode,
        auth_method: IntegrationAuthMethod | None,
        kind: IntegrationKind = IntegrationKind.API,
        app_type: ExternalAppType = ExternalAppType.CUSTOM,
        header_template: dict[str, str] | None = None,
        provider_mode: IntegrationOAuthProviderMode | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        pkce: bool | None = None,
        registration: dict[str, Any] | None = None,
        scopes: list[str] | None = None,
    ) -> Integration:
        name = f"Test integration {uuid4().hex[:8]}"
        integration = Integration(
            kind=kind,
            name=name,
            auth_mode=auth_mode,
            auth_method=auth_method,
            header_template=header_template,
        )
        if kind is IntegrationKind.MCP:
            server = MCPServer(
                owner="integration-test@example.com",
                name=name,
                server_url="https://mcp.example.test/mcp",
                transport=MCPTransport.STREAMABLE_HTTP,
                auth_type=MCPAuthenticationType.OAUTH,
                auth_performer=MCPAuthenticationPerformer.PER_USER,
            )
            db_session.add(server)
            db_session.flush()
            server_ids.append(server.id)
            integration.mcp_server_id = server.id
        else:
            app = ExternalApp(
                name=name,
                app_type=app_type,
                upstream_url_patterns=[],
                auth_template={"Authorization": "Bearer {access_token}"},
                organization_credentials={},
            )
            db_session.add(app)
            db_session.flush()
            app_ids.append(app.id)
            integration.external_app_id = app.id
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
        return integration

    try:
        yield make
    finally:
        db_session.rollback()
        # The integration and its rows go by cascade.
        db_session.execute(delete(MCPServer).where(MCPServer.id.in_(server_ids)))
        db_session.execute(delete(ExternalApp).where(ExternalApp.id.in_(app_ids)))
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
        self.delay_s = 0.0
        # Send the body form-encoded, as some MCP servers do.
        self.form_encoded = False
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def send(self, request: httpx.Request, *, mcp: bool) -> httpx.Response:  # noqa: ARG002
        with self._lock:
            self.requests.append(request)
        if self.delay_s:
            time.sleep(self.delay_s)
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
