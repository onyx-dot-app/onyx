"""Migration 730bce2814a0 writes no actions for an API integration. A read
builds them from the settings and writes nothing; an admin save writes them."""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import (
    get_session_with_current_tenant,
    get_session_with_tenant,
)
from onyx.db.models import IntegrationAction, Tool, User
from onyx.integrations.actions import integration_actions
from onyx.integrations.chat_tools import build_integration_chat_tools
from onyx.integrations.models import ActionSettings, ApprovalMode, EffectivePolicy
from onyx.integrations.service import agent_catalog
from onyx.server.features.integrations import admin_api
from onyx.server.features.integrations.models import IntegrationActionsUpdate
from onyx.tools.models import IntegrationChatRequest, IntegrationLinkConfiguration
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_openapi_integration,
)

ORDERS_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Orders", "description": "Orders", "version": "1"},
    "servers": [{"url": "https://orders.example.com"}],
    "paths": {
        "/orders": {
            "get": {"operationId": "listOrders", "summary": "List orders"},
            "post": {"operationId": "createOrder", "summary": "Create an order"},
        }
    },
}
NO_ACTIONS_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Empty", "version": "1"},
    "servers": [{"url": "https://empty.example.com"}],
    "paths": {},
}


@pytest.fixture
def created(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[int], None, None]:
    integration_ids: list[int] = []
    try:
        yield integration_ids
    finally:
        delete_integrations(db_session, integration_ids)


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("first-read-admin", is_admin=True)


@pytest.fixture
def member(make_test_user: MakeTestUser) -> User:
    return make_test_user("first-read-member")


def _migrated_openapi(
    db_session: Session, created: list[int], spec: dict[str, Any]
) -> int:
    """An OpenAPI integration as the migration leaves it: no action rows. The
    app refuses a spec with no actions, so the tool gets ``spec`` after the
    create, as an old tool row can hold it."""
    integration, tool = make_openapi_integration(db_session, openapi_schema=ORDERS_SPEC)
    created.append(integration.id)
    db_session.execute(
        update(Tool).where(Tool.id == tool.id).values(openapi_schema=spec)
    )
    give_access(db_session, [integration])
    db_session.execute(
        delete(IntegrationAction).where(
            IntegrationAction.integration_id == integration.id
        )
    )
    db_session.commit()
    return integration.id


def _stored_keys(db_session: Session, integration_id: int) -> list[str]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(IntegrationAction.key)
            .where(IntegrationAction.integration_id == integration_id)
            .order_by(IntegrationAction.key)
        )
    )


def test_the_admin_actions_tab_lists_the_actions_and_a_save_writes_them(
    db_session: Session, admin: User, created: list[int]
) -> None:
    integration_id = _migrated_openapi(db_session, created, ORDERS_SPEC)

    with get_session_with_current_tenant() as request_session:
        actions = admin_api.get_integration_actions(
            integration_id, admin, request_session
        ).actions

    assert [(a.key, a.default_policy.value) for a in actions] == [
        ("listOrders", "allow"),
        ("createOrder", "ask"),
    ]
    assert _stored_keys(db_session, integration_id) == []

    with get_session_with_current_tenant() as request_session:
        admin_api.set_integration_actions(
            integration_id,
            IntegrationActionsUpdate(actions={"createOrder": EffectivePolicy.BLOCKED}),
            admin,
            request_session,
        )

    assert _stored_keys(db_session, integration_id) == ["createOrder", "listOrders"]


def test_chat_offers_the_actions(
    db_session: Session, member: User, created: list[int]
) -> None:
    integration_id = _migrated_openapi(db_session, created, ORDERS_SPEC)

    with get_session_with_current_tenant() as request_session:
        tools = build_integration_chat_tools(
            request_session,
            member,
            IntegrationChatRequest(
                persona_id=7,
                integration_links=[
                    IntegrationLinkConfiguration(
                        integration_id=integration_id,
                        action_settings=ActionSettings(),
                    )
                ],
                approval_mode=ApprovalMode.INTERACTIVE,
            ),
        )

    assert sorted(tool.name for tool in tools) == [
        f"custom__{integration_id}__createOrder",
        f"custom__{integration_id}__listOrders",
    ]


def test_a_spec_with_no_actions_gives_none(
    db_session: Session, created: list[int]
) -> None:
    integration_id = _migrated_openapi(db_session, created, NO_ACTIONS_SPEC)

    with get_session_with_current_tenant() as request_session:
        assert integration_actions(integration_id, request_session) == []

    assert (
        db_session.scalar(
            select(func.count())
            .select_from(IntegrationAction)
            .where(IntegrationAction.integration_id == integration_id)
        )
        == 0
    )


def test_the_agent_catalog_lists_the_actions(
    db_session: Session, member: User, created: list[int]
) -> None:
    integration_id = _migrated_openapi(db_session, created, ORDERS_SPEC)

    with get_session_with_current_tenant() as request_session:
        catalog = agent_catalog(member, request_session)

    [option] = [option for option in catalog if option.id == integration_id]
    assert sorted(action.key for action in option.actions) == [
        "createOrder",
        "listOrders",
    ]


def test_a_reader_with_no_tenant_context_reads_its_session_tenant(
    db_session: Session, created: list[int]
) -> None:
    """The sandbox proxy opens a session for a tenant and sets no tenant
    context, which a multi-tenant lookup refuses."""
    integration_id = _migrated_openapi(db_session, created, ORDERS_SPEC)

    token = CURRENT_TENANT_ID_CONTEXTVAR.set(None)
    try:
        with (
            patch("shared_configs.contextvars.MULTI_TENANT", True),
            get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as proxy_session,
        ):
            actions = integration_actions(integration_id, proxy_session)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert sorted(a.key for a in actions) == ["createOrder", "listOrders"]
    assert _stored_keys(db_session, integration_id) == []
