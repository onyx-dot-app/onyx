"""The action sync of each integration kind against a real Postgres.

For each API shape, ``discover_actions`` must give what the old code exposes,
and ``sync_integration_actions__no_commit`` must write ``integration_action``
rows that a second run leaves alone."""

import datetime
from collections.abc import Generator
from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ActionPolicy,
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMode,
    IntegrationKind,
)
from onyx.db.integration import (
    create_openapi_tool_row__no_commit,
    list_integration_actions,
    replace_integration_actions__no_commit,
)
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationAction,
    Tool,
)
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.integrations.kinds.api import (
    ApiKindHandler,
    sync_integration_actions__no_commit,
)
from onyx.integrations.models import IntegrationActionSpec
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_method_specs,
)

Snapshot = dict[str, tuple[int, datetime.datetime, str | None]]


def _openapi_spec(host: str) -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Orders", "description": "Orders API", "version": "1"},
        "servers": [{"url": f"https://{host}/v1"}],
        "paths": {
            "/orders": {
                "get": {"operationId": "listOrders", "summary": "List orders"},
                "post": {"operationId": "createOrder", "summary": "Create an order"},
            },
            "/orders/{order_id}": {
                "delete": {
                    "operationId": "deleteOrder",
                    "summary": "Delete an order",
                    "parameters": [
                        {
                            "name": "order_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                },
            },
        },
    }


class Created:
    """Rows a test made, deleted at teardown."""

    def __init__(self) -> None:
        self.integration_ids: list[int] = []
        self.tool_ids: list[int] = []
        self.external_app_ids: list[int] = []


@pytest.fixture
def created(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[Created, None, None]:
    rows = Created()
    yield rows
    db_session.rollback()
    if rows.tool_ids:
        db_session.execute(delete(Tool).where(Tool.id.in_(rows.tool_ids)))
    if rows.external_app_ids:
        db_session.execute(
            delete(ExternalApp).where(ExternalApp.id.in_(rows.external_app_ids))
        )
    if rows.integration_ids:
        db_session.execute(
            delete(Integration).where(Integration.id.in_(rows.integration_ids))
        )
    db_session.commit()


def _integration(
    db_session: Session,
    created: Created,
    kind: IntegrationKind,
    *,
    external_app_id: int | None = None,
    tool_id: int | None = None,
) -> Integration:
    integration = Integration(
        kind=kind,
        name=f"sync-{uuid4().hex[:8]}",
        auth_mode=IntegrationAuthMode.NONE,
        external_app_id=external_app_id,
        tool_id=tool_id,
    )
    db_session.add(integration)
    db_session.flush()
    created.integration_ids.append(integration.id)
    return integration


def _openapi_tool(db_session: Session, created: Created) -> tuple[Integration, Tool]:
    tool = create_openapi_tool_row__no_commit(
        name=f"orders-{uuid4().hex[:8]}",
        description="Orders",
        user_id=None,
        openapi_spec=_openapi_spec(f"orders-{uuid4().hex[:8]}.example.com"),
        db_session=db_session,
    )
    created.tool_ids.append(tool.id)
    integration = _integration(
        db_session, created, IntegrationKind.API, tool_id=tool.id
    )
    db_session.commit()
    return integration, tool


def _external_app(
    db_session: Session,
    created: Created,
    app_type: ExternalAppType,
    patterns: list[str],
) -> tuple[Integration, ExternalApp]:
    app = ExternalApp(
        name=f"app-{uuid4().hex[:8]}",
        app_type=app_type,
        upstream_url_patterns=patterns,
    )
    db_session.add(app)
    db_session.flush()
    created.external_app_ids.append(app.id)
    integration = _integration(
        db_session, created, IntegrationKind.API, external_app_id=app.id
    )
    db_session.commit()
    return integration, app


def _snapshot(db_session: Session, integration_id: int) -> Snapshot:
    db_session.expire_all()
    return {
        a.key: (a.id, a.updated_at, a.description)
        for a in list_integration_actions(integration_id, db_session)
    }


def _sync(db_session: Session, integration: Integration) -> None:
    sync_integration_actions__no_commit(integration, db_session)
    db_session.commit()


def _assert_idempotent(db_session: Session, integration: Integration) -> Snapshot:
    _sync(db_session, integration)
    first = _snapshot(db_session, integration.id)
    _sync(db_session, integration)
    assert _snapshot(db_session, integration.id) == first
    return first


# OpenAPI tool


def test_openapi_discover_actions_equal_the_method_specs(
    db_session: Session, created: Created
) -> None:
    integration, tool = _openapi_tool(db_session, created)
    if tool.openapi_schema is None:
        raise AssertionError("tool has no schema")

    specs = ApiKindHandler().discover_actions(integration, db_session)

    method_specs = openapi_to_method_specs(tool.openapi_schema)
    assert [(s.key, s.description, s.http_method, s.path_template) for s in specs] == [
        (m.raw_name, m.summary, m.method.upper(), m.path) for m in method_specs
    ]


def test_openapi_sync_writes_updates_and_deletes(
    db_session: Session, created: Created
) -> None:
    integration, tool = _openapi_tool(db_session, created)

    first = _assert_idempotent(db_session, integration)
    assert set(first) == {"listOrders", "createOrder", "deleteOrder"}
    policies = {
        a.key: a.default_policy
        for a in list_integration_actions(integration.id, db_session)
    }
    assert policies == {
        "listOrders": IntegrationActionPolicyValue.ALLOW,
        "createOrder": IntegrationActionPolicyValue.ASK,
        "deleteOrder": IntegrationActionPolicyValue.ASK,
    }

    schema = deepcopy(tool.openapi_schema)
    if schema is None:
        raise AssertionError("tool has no schema")
    del schema["paths"]["/orders/{order_id}"]
    schema["paths"]["/orders"]["get"]["summary"] = "List all orders"
    tool.openapi_schema = schema
    db_session.commit()
    _sync(db_session, integration)

    after = _snapshot(db_session, integration.id)
    assert set(after) == {"listOrders", "createOrder"}
    assert after["listOrders"][0] == first["listOrders"][0]
    assert after["listOrders"][2] == "List all orders"
    assert after["createOrder"] == first["createOrder"]


def test_openapi_sync_reads_the_settings_committed_before_its_lock(
    db_session: Session, created: Created
) -> None:
    integration, tool = _openapi_tool(db_session, created)
    _sync(db_session, integration)
    # This session holds the old schema in memory.
    assert tool.openapi_schema is not None
    assert "/orders/{order_id}" in tool.openapi_schema["paths"]

    with get_session_with_current_tenant() as other_session:
        other_tool = other_session.get(Tool, tool.id)
        other_integration = other_session.get(Integration, integration.id)
        if other_tool is None or other_integration is None:
            raise AssertionError("rows are gone")
        schema = deepcopy(other_tool.openapi_schema)
        if schema is None:
            raise AssertionError("tool has no schema")
        del schema["paths"]["/orders/{order_id}"]
        other_tool.openapi_schema = schema
        _sync(other_session, other_integration)

    _sync(db_session, integration)

    assert set(_snapshot(db_session, integration.id)) == {"listOrders", "createOrder"}


# External apps


def test_preset_discover_actions_equal_the_catalog(
    db_session: Session, created: Created
) -> None:
    integration, _app = _external_app(
        db_session, created, ExternalAppType.LINEAR, [r"https://api\.linear\.app/.*"]
    )

    specs = ApiKindHandler().discover_actions(integration, db_session)

    catalog = get_endpoint_catalog(ExternalAppType.LINEAR)
    assert [(s.key, s.display_name, s.description) for s in specs] == [
        (e.id.value, e.normalised_name, e.description) for e in catalog
    ]
    assert [s.read_only for s in specs] == [
        e.default_policy is ActionPolicy.ALWAYS for e in catalog
    ]


def test_preset_sync_is_idempotent(db_session: Session, created: Created) -> None:
    integration, _app = _external_app(
        db_session, created, ExternalAppType.LINEAR, [r"https://api\.linear\.app/.*"]
    )

    first = _assert_idempotent(db_session, integration)

    assert set(first) == {
        e.id.value for e in get_endpoint_catalog(ExternalAppType.LINEAR)
    }
    assert all(
        a.source is IntegrationActionSource.EXTERNAL_APP
        for a in list_integration_actions(integration.id, db_session)
    )


def test_custom_app_sync_writes_one_whole_domain_action(
    db_session: Session, created: Created
) -> None:
    integration, _app = _external_app(
        db_session, created, ExternalAppType.CUSTOM, ["https://internal.example.com/**"]
    )

    first = _assert_idempotent(db_session, integration)

    assert list(first) == ["unspecified"]
    (action,) = list_integration_actions(integration.id, db_session)
    assert action.display_name == integration.name
    assert action.default_policy is IntegrationActionPolicyValue.ASK


# The replace function


def _spec(key: str, description: str) -> IntegrationActionSpec:
    return IntegrationActionSpec(
        key=key,
        source=IntegrationActionSource.OPENAPI,
        display_name=key,
        description=description,
        read_only=None,
        default_policy=IntegrationActionPolicyValue.ASK,
    )


def test_replace_keeps_other_sources_and_first_duplicate(
    db_session: Session, created: Created
) -> None:
    integration, _app = _external_app(
        db_session, created, ExternalAppType.CUSTOM, ["https://internal.example.com/**"]
    )
    db_session.add(
        IntegrationAction(
            integration_id=integration.id,
            key="from_mcp",
            source=IntegrationActionSource.MCP,
            display_name="from_mcp",
        )
    )
    db_session.commit()

    replace_integration_actions__no_commit(
        integration.id,
        IntegrationActionSource.OPENAPI,
        [_spec("a", "first"), _spec("a", "second")],
        db_session,
    )
    db_session.commit()

    actions = {a.key: a for a in list_integration_actions(integration.id, db_session)}
    assert set(actions) == {"from_mcp", "a"}
    assert actions["a"].description == "first"
