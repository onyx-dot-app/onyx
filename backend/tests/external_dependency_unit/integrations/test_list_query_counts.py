"""The integration lists and ``GET /tool`` read each kind of row in one query
for all integrations, so their query count does not grow with the number of
integrations."""

from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationAuthMethod, IntegrationAuthMode
from onyx.db.models import Integration, Persona, Persona__Integration, User
from onyx.integrations.connections import connect_with_fields__no_commit
from onyx.server.features.integrations import admin_api, api
from onyx.server.features.integrations.models import (
    IntegrationCreate,
    McpServerConfigInput,
    OpenApiConfigInput,
)
from onyx.server.features.persona.api import get_persona
from onyx.server.features.tool import api as tool_api
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_openapi_integration,
)


def _openapi_spec(name: str) -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": name, "description": name, "version": "1.0"},
        "servers": [{"url": "https://weather.example.com"}],
        "paths": {
            "/forecast": {
                "get": {"operationId": "get_forecast", "summary": "Forecast"},
                "post": {"operationId": "set_alert", "summary": "Alert"},
            }
        },
    }


@contextmanager
def _counting(db_session: Session) -> Iterator[list[str]]:
    statements: list[str] = []
    connection = db_session.connection()

    def record(_conn: Connection, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", record)


def _query_count(
    db_session: Session, users: list[User], read: Callable[[], object]
) -> int:
    db_session.expire_all()
    for user in users:
        db_session.refresh(user)
    with _counting(db_session) as statements:
        read()
    return len(statements)


def _add_integrations(
    db_session: Session, admin: User, member: User, ids: list[int]
) -> None:
    for _ in range(5):
        name = f"count-api-{uuid4().hex[:8]}"
        detail = admin_api.create_integration(
            IntegrationCreate(
                for_organization=True,
                name=name,
                auth_mode=IntegrationAuthMode.SHARED,
                auth_method=IntegrationAuthMethod.API_KEY,
                header_template={"X-Api-Key": "{api_key}"},
                config=OpenApiConfigInput(openapi_spec=_openapi_spec(name)),
            ),
            admin,
            db_session,
        )
        ids.append(detail.id)
        integration = db_session.get(Integration, detail.id)
        assert integration is not None
        connect_with_fields__no_commit(
            integration, None, {"api_key": "org-key"}, db_session
        )
        db_session.commit()
    with patch("onyx.integrations.service.discover_mcp_tools", return_value=[]):
        ids.extend(
            admin_api.create_integration(
                IntegrationCreate(
                    for_organization=True,
                    name=f"count-mcp-{uuid4().hex[:8]}",
                    auth_mode=IntegrationAuthMode.NONE,
                    config=McpServerConfigInput(
                        server_url="https://mcp.example.com/mcp"
                    ),
                ),
                admin,
                db_session,
            ).id
            for _ in range(3)
        )
    for index in range(2):
        detail = admin_api.create_integration(
            IntegrationCreate(
                for_organization=True,
                name=f"count-mcp-key-{uuid4().hex[:8]}",
                auth_mode=IntegrationAuthMode.INDIVIDUAL,
                auth_method=IntegrationAuthMethod.API_KEY,
                header_template={"Authorization": "Bearer {api_key}"},
                config=McpServerConfigInput(server_url="https://mcp.example.com/mcp"),
            ),
            admin,
            db_session,
        )
        ids.append(detail.id)
        if index == 0:
            integration = db_session.get(Integration, detail.id)
            assert integration is not None
            connect_with_fields__no_commit(
                integration, member, {"api_key": "mine"}, db_session
            )
            db_session.commit()


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("count-admin", is_admin=True)


@pytest.fixture
def member(make_test_user: MakeTestUser) -> User:
    return make_test_user("count-member")


@pytest.fixture
def created(
    db_session: Session,
    admin: User,  # noqa: ARG001
    member: User,  # noqa: ARG001
) -> Generator[list[int], None, None]:
    ids: list[int] = []
    try:
        yield ids
    finally:
        delete_integrations(db_session, ids)


def test_list_views_do_not_query_once_per_integration(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    views: dict[str, tuple[list[User], Callable[[], object]]] = {
        "admin list": (
            [admin],
            lambda: admin_api.list_integrations_admin(admin, db_session),
        ),
        "member list": (
            [member],
            lambda: api.list_integrations_for_member(member, db_session),
        ),
        "agent catalog": (
            [member],
            lambda: api.get_agent_catalog(member, db_session),
        ),
        "GET /tool": ([member], lambda: tool_api.list_tools(db_session, member)),
    }
    _add_integrations(db_session, admin, member, created)
    before = {
        name: _query_count(db_session, users, read)
        for name, (users, read) in views.items()
    }
    _add_integrations(db_session, admin, member, created)
    after = {
        name: _query_count(db_session, users, read)
        for name, (users, read) in views.items()
    }
    assert after == before


def test_persona_detail_batches_openapi_snapshots(
    db_session: Session, admin: User, created: list[int]
) -> None:
    persona = Persona(name="snapshot-count", description="", user_id=admin.id)
    db_session.add(persona)
    db_session.commit()
    counts: list[int] = []
    expected: dict[int, dict[str, Any]] = {}
    try:
        for size in (2, 10):
            for i in range(len(created), size):
                integration, tool = make_openapi_integration(
                    db_session, openapi_schema=_openapi_spec(str(i))
                )
                created.append(integration.id)
                give_access(db_session, [integration], owner_user_id=admin.id)
                db_session.add(
                    Persona__Integration(
                        persona_id=persona.id, integration_id=integration.id
                    )
                )
                db_session.flush()
                expected[tool.id] = tool_api.openapi_tool_snapshot(
                    tool, integration, db_session
                ).model_dump()
            db_session.commit()

            def read(expected_size: int = size) -> None:
                snapshot = get_persona(persona.id, admin, db_session)
                assert len(snapshot.tools) == expected_size
                assert {
                    tool.id: tool.model_dump() for tool in snapshot.tools
                } == expected

            counts.append(_query_count(db_session, [admin], read))
        assert counts[0] == counts[1], counts
    finally:
        db_session.delete(persona)
        db_session.commit()
