"""Rows for tests of integrations: an integration with its kind row and an
optional OAuth client."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    MCPTransport,
)
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationOAuthClient,
    MCPServer,
)


def _add_integration(
    db_session: Session,
    *,
    kind: IntegrationKind,
    name: str,
    auth_mode: IntegrationAuthMode,
    auth_method: IntegrationAuthMethod | None,
    header_template: dict[str, str] | None,
    oauth_client: IntegrationOAuthClient | None,
    mcp_server_id: int | None = None,
    external_app_id: int | None = None,
) -> Integration:
    integration = Integration(
        kind=kind,
        name=name,
        auth_mode=auth_mode,
        auth_method=auth_method,
        header_template=header_template,
        mcp_server_id=mcp_server_id,
        external_app_id=external_app_id,
    )
    db_session.add(integration)
    db_session.flush()
    if oauth_client is not None:
        oauth_client.integration_id = integration.id
        db_session.add(oauth_client)
        db_session.flush()
    return integration


def make_mcp_integration(
    db_session: Session,
    *,
    server_url: str = "https://mcp.example.test/mcp",
    name: str | None = None,
    auth_mode: IntegrationAuthMode = IntegrationAuthMode.NONE,
    auth_method: IntegrationAuthMethod | None = None,
    header_template: dict[str, str] | None = None,
    oauth_client: IntegrationOAuthClient | None = None,
) -> tuple[Integration, MCPServer]:
    """``oauth_client`` is an unsaved row; this function links and saves it."""
    integration_name = name or f"mcp-{uuid4().hex[:8]}"
    server = MCPServer(
        owner="admin@example.com",
        name=integration_name,
        server_url=server_url,
        transport=MCPTransport.STREAMABLE_HTTP,
    )
    db_session.add(server)
    db_session.flush()
    integration = _add_integration(
        db_session,
        kind=IntegrationKind.MCP,
        name=integration_name,
        auth_mode=auth_mode,
        auth_method=auth_method,
        header_template=header_template,
        oauth_client=oauth_client,
        mcp_server_id=server.id,
    )
    db_session.commit()
    return integration, server


def make_app_integration(
    db_session: Session,
    *,
    name: str | None = None,
    app_type: ExternalAppType = ExternalAppType.CUSTOM,
    auth_template: dict[str, Any] | None = None,
    organization_credentials: dict[str, Any] | None = None,
    auth_mode: IntegrationAuthMode = IntegrationAuthMode.INDIVIDUAL,
    auth_method: IntegrationAuthMethod | None = None,
    header_template: dict[str, str] | None = None,
    oauth_client: IntegrationOAuthClient | None = None,
) -> tuple[Integration, ExternalApp]:
    """An external app integration. ``oauth_client`` is an unsaved row; this
    function links and saves it."""
    app_name = name or f"app-{uuid4().hex[:8]}"
    app = ExternalApp(
        name=app_name,
        app_type=app_type,
        upstream_url_patterns=[],
        auth_template=auth_template or {},
        organization_credentials=organization_credentials or {},
    )
    db_session.add(app)
    db_session.flush()
    integration = _add_integration(
        db_session,
        kind=IntegrationKind.API,
        name=app_name,
        auth_mode=auth_mode,
        auth_method=auth_method,
        header_template=header_template,
        oauth_client=oauth_client,
        external_app_id=app.id,
    )
    db_session.commit()
    return integration, app


def delete_integrations(db_session: Session, integration_ids: Sequence[int]) -> None:
    """Delete the integrations with their kind rows. The other rows of an
    integration go by cascade."""
    db_session.rollback()
    if not integration_ids:
        return
    integrations = db_session.scalars(
        select(Integration).where(Integration.id.in_(integration_ids))
    ).all()
    server_ids = [i.mcp_server_id for i in integrations if i.mcp_server_id]
    app_ids = [i.external_app_id for i in integrations if i.external_app_id]
    db_session.execute(delete(Integration).where(Integration.id.in_(integration_ids)))
    db_session.execute(delete(MCPServer).where(MCPServer.id.in_(server_ids)))
    db_session.execute(delete(ExternalApp).where(ExternalApp.id.in_(app_ids)))
    db_session.commit()
