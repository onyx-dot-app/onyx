from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.db.enums import IntegrationActionSource
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationAction,
    MCPServer,
    Plugin,
    Plugin__Integration,
    Tool,
)
from onyx.integrations.models import IntegrationActionSpec


def get_integration_by_id(
    integration_id: int, db_session: Session
) -> Integration | None:
    return db_session.get(Integration, integration_id)


def list_enabled_integrations_by_id(
    db_session: Session, integration_ids: Collection[int]
) -> list[Integration]:
    if not integration_ids:
        return []
    return list(
        db_session.scalars(
            select(Integration)
            .where(Integration.id.in_(integration_ids), Integration.enabled.is_(True))
            .order_by(Integration.id)
        ).all()
    )


def list_integrations(db_session: Session) -> list[Integration]:
    return list(db_session.scalars(select(Integration).order_by(Integration.id)).all())


def _plugin_ids_by(
    key: InstrumentedAttribute[int] | InstrumentedAttribute[int | None],
    ids: Collection[int],
    db_session: Session,
) -> dict[int, list[UUID]]:
    if not ids:
        return {}
    plugin_ids: dict[int, list[UUID]] = {}
    for row_id, plugin_id in db_session.execute(
        select(key, Plugin__Integration.plugin_id)
        .join(Integration, Integration.id == Plugin__Integration.integration_id)
        .join(Plugin, Plugin.id == Plugin__Integration.plugin_id)
        .where(key.in_(ids))
        .order_by(Plugin.created_at, Plugin.id)
    ).tuples():
        if row_id is not None:
            plugin_ids.setdefault(row_id, []).append(plugin_id)
    return plugin_ids


def get_integration_plugin_ids(
    integration_ids: Collection[int], db_session: Session
) -> dict[int, list[UUID]]:
    """The plugins that hold each integration, oldest first."""
    return _plugin_ids_by(Integration.id, integration_ids, db_session)


def get_mcp_server_plugin_ids(
    mcp_server_ids: Collection[int], db_session: Session
) -> dict[int, list[UUID]]:
    return _plugin_ids_by(Integration.mcp_server_id, mcp_server_ids, db_session)


def get_tool_plugin_ids(
    tool_ids: Collection[int], db_session: Session
) -> dict[int, list[UUID]]:
    return _plugin_ids_by(Integration.tool_id, tool_ids, db_session)


def get_mcp_server_for_integration(
    integration_id: int, db_session: Session
) -> MCPServer | None:
    return db_session.scalar(
        select(MCPServer)
        .join(Integration, Integration.mcp_server_id == MCPServer.id)
        .where(Integration.id == integration_id)
    )


def get_external_app_for_integration(
    integration_id: int, db_session: Session
) -> ExternalApp | None:
    return db_session.scalar(
        select(ExternalApp)
        .join(Integration, Integration.external_app_id == ExternalApp.id)
        .where(Integration.id == integration_id)
    )


def _enabled(integration_id: int | None) -> ColumnElement[bool]:
    enabled = Integration.enabled.is_(True)
    if integration_id is None:
        return enabled
    return and_(enabled, Integration.id == integration_id)


def list_enabled_mcp_server_urls(
    db_session: Session, integration_id: int | None = None
) -> list[tuple[int, str]]:
    """``(integration_id, server_url)`` of each enabled MCP integration, or of
    only ``integration_id``."""
    return list(
        db_session.execute(
            select(Integration.id, MCPServer.server_url)
            .join(MCPServer, MCPServer.id == Integration.mcp_server_id)
            .where(_enabled(integration_id))
            .order_by(Integration.id)
        ).tuples()
    )


def list_enabled_openapi_schemas(
    db_session: Session, integration_id: int | None = None
) -> list[tuple[int, dict[str, Any] | None]]:
    """``(integration_id, openapi_schema)`` of each enabled OpenAPI integration,
    or of only ``integration_id``."""
    return list(
        db_session.execute(
            select(Integration.id, Tool.openapi_schema)
            .join(Tool, Tool.id == Integration.tool_id)
            .where(_enabled(integration_id))
            .order_by(Integration.id)
        ).tuples()
    )


def list_enabled_external_apps(
    db_session: Session, integration_id: int | None = None
) -> list[tuple[int, ExternalApp]]:
    """``(integration_id, external_app)`` of each enabled preset or custom app,
    or of only ``integration_id``."""
    return list(
        db_session.execute(
            select(Integration.id, ExternalApp)
            .join(ExternalApp, ExternalApp.id == Integration.external_app_id)
            .where(_enabled(integration_id))
            .order_by(Integration.id)
        ).tuples()
    )


def get_openapi_tool_for_integration(
    integration_id: int, db_session: Session
) -> Tool | None:
    return db_session.scalar(
        select(Tool)
        .join(Integration, Integration.tool_id == Tool.id)
        .where(
            Integration.id == integration_id,
            Tool.openapi_schema.is_not(None),
        )
    )


def list_integration_actions(
    integration_id: int, db_session: Session
) -> list[IntegrationAction]:
    return list(
        db_session.scalars(
            select(IntegrationAction)
            .where(IntegrationAction.integration_id == integration_id)
            .order_by(IntegrationAction.id)
        ).all()
    )


def _apply_spec(action: IntegrationAction, spec: IntegrationActionSpec) -> None:
    action.source = spec.source
    action.display_name = spec.display_name
    action.description = spec.description
    action.read_only = spec.read_only
    action.default_policy = spec.default_policy
    action.input_schema = spec.input_schema
    action.output_schema = spec.output_schema
    action.http_method = spec.http_method
    action.path_template = spec.path_template


def lock_integration__no_commit(integration_id: int, db_session: Session) -> None:
    """Locks the integration row, then expires the session, so the reads that
    follow see what other transactions committed before the lock."""
    db_session.flush()
    db_session.execute(
        select(Integration.id).where(Integration.id == integration_id).with_for_update()
    )
    db_session.expire_all()


def replace_integration_actions__no_commit(
    integration_id: int,
    source: IntegrationActionSource,
    specs: Sequence[IntegrationActionSpec],
    db_session: Session,
) -> None:
    """Locks the integration row, so two syncs of one integration run one at a
    time. If two specs have the same key, the first one wins."""
    db_session.execute(
        select(Integration.id).where(Integration.id == integration_id).with_for_update()
    )
    existing_by_key = {
        action.key: action
        for action in list_integration_actions(integration_id, db_session)
    }

    kept_keys: set[str] = set()
    for spec in specs:
        if spec.key in kept_keys:
            continue
        kept_keys.add(spec.key)
        existing = existing_by_key.get(spec.key)
        if existing is not None:
            _apply_spec(existing, spec)
            continue
        db_session.add(
            IntegrationAction(
                integration_id=integration_id,
                key=spec.key,
                source=spec.source,
                display_name=spec.display_name,
                description=spec.description,
                read_only=spec.read_only,
                default_policy=spec.default_policy,
                input_schema=spec.input_schema,
                output_schema=spec.output_schema,
                http_method=spec.http_method,
                path_template=spec.path_template,
            )
        )

    stale_ids = [
        action.id
        for key, action in existing_by_key.items()
        if action.source == source and key not in kept_keys
    ]
    if stale_ids:
        db_session.execute(
            delete(IntegrationAction)
            .where(IntegrationAction.id.in_(stale_ids))
            .execution_options(synchronize_session="fetch")
        )
    db_session.flush()
