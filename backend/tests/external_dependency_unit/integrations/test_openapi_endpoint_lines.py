"""Endpoint lines through the admin API: a create from typed lines, and line
edits of an imported spec that keep what the spec said about the other
operations."""

import json
from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
import yaml
from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationAuthMode
from onyx.db.integration import (
    get_api_app_for_integration,
    get_openapi_tool_for_integration,
)
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.models import EffectivePolicy
from onyx.integrations.openapi_endpoints import EndpointLineError
from onyx.server.features.integrations import admin_api
from onyx.server.features.integrations.models import (
    IntegrationActionsUpdate,
    IntegrationCreate,
    IntegrationUpdate,
    OpenApiConfigInput,
    OpenApiConfigView,
    OpenApiEndpointsRequest,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import delete_integrations

BASE_URL = "https://tickets.example.com/api"

IMPORTED: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Tickets", "description": "Tickets", "version": "2.0"},
    "servers": [{"url": "https://old.example.com/api"}],
    "paths": {
        "/tickets": {
            "get": {
                "operationId": "listTickets",
                "summary": "List tickets",
                "description": "Lists the open tickets.",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "schema": {"type": "string", "enum": ["open", "closed"]},
                    }
                ],
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createTicket",
                "summary": "Create a ticket",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"title": {"type": "string"}},
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/tickets/{id}": {
            "get": {
                "operationId": "getTicket",
                "summary": "Read a ticket",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"description": "OK"}},
            },
            "delete": {
                "operationId": "deleteTicket",
                "summary": "Delete a ticket",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {}}
                ],
                "responses": {"204": {"description": "Deleted"}},
            },
        },
    },
}


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("endpoint-lines-admin", is_admin=True)


@pytest.fixture
def created(db_session: Session) -> Generator[list[int], None, None]:
    ids: list[int] = []
    yield ids
    delete_integrations(db_session, ids)


def _create(
    db_session: Session, admin: User, created: list[int], config: OpenApiConfigInput
) -> int:
    detail = admin_api.create_integration(
        IntegrationCreate(
            name=f"tickets-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.NONE,
            config=config,
        ),
        admin,
        db_session,
    )
    created.append(detail.id)
    return detail.id


def _view(db_session: Session, admin: User, integration_id: int) -> OpenApiConfigView:
    config = admin_api.get_integration_admin(integration_id, admin, db_session).config
    assert isinstance(config, OpenApiConfigView)
    return config


def _operations(document: str) -> dict[str, dict[str, Any]]:
    spec = yaml.safe_load(document)
    return {
        operation["operationId"]: operation
        for item in spec["paths"].values()
        for operation in item.values()
    }


def _action_keys(db_session: Session, admin: User, integration_id: int) -> set[str]:
    return {
        action.key
        for action in admin_api.get_integration_actions(
            integration_id, admin, db_session
        ).actions
    }


def test_typed_lines_make_a_document_and_actions(
    db_session: Session, admin: User, created: list[int]
) -> None:
    integration_id = _create(
        db_session,
        admin,
        created,
        OpenApiConfigInput(
            base_url=BASE_URL,
            endpoints=[
                "GET /tickets/{id} Read a ticket",
                "",
                "GET /tickets?status&limit List tickets",
                "post /tickets Create a ticket",
            ],
        ),
    )

    view = _view(db_session, admin, integration_id)
    assert view.base_url == BASE_URL
    assert view.endpoints == [
        "GET /tickets/{id} Read a ticket",
        "GET /tickets?status&limit List tickets",
        "POST /tickets Create a ticket",
    ]
    operations = _operations(view.openapi_document)
    assert operations["get_tickets_id"]["parameters"] == [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    ]
    assert [
        (param["name"], param["required"])
        for param in operations["get_tickets"]["parameters"]
    ] == [("status", False), ("limit", False)]
    assert operations["post_tickets"]["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"type": "object", "additionalProperties": True}
    assert "requestBody" not in operations["get_tickets"]
    assert _action_keys(db_session, admin, integration_id) == {
        "get_tickets_id",
        "get_tickets",
        "post_tickets",
    }

    app = get_api_app_for_integration(integration_id, db_session)
    tool = get_openapi_tool_for_integration(integration_id, db_session)
    assert app is not None and app.base_url == BASE_URL
    assert tool is not None and tool.openapi_schema == json.loads(view.openapi_document)


def test_a_line_edit_keeps_the_rest_of_an_imported_yaml_spec(
    db_session: Session, admin: User, created: list[int]
) -> None:
    document = yaml.safe_dump(IMPORTED, sort_keys=False)
    imported = admin_api.import_openapi_spec(
        OpenApiEndpointsRequest(openapi_document=document), admin
    )
    assert imported.base_url == "https://old.example.com/api"
    assert imported.endpoints == [
        "GET /tickets?status List tickets",
        "POST /tickets Create a ticket",
        "GET /tickets/{id} Read a ticket",
        "DELETE /tickets/{id} Delete a ticket",
    ]
    integration_id = _create(
        db_session,
        admin,
        created,
        OpenApiConfigInput(
            openapi_document=imported.openapi_document,
            base_url=BASE_URL,
            endpoints=imported.endpoints,
        ),
    )
    admin_api.set_integration_actions(
        integration_id,
        IntegrationActionsUpdate(
            actions={
                "createTicket": EffectivePolicy.BLOCKED,
                "getTicket": EffectivePolicy.ASK,
            }
        ),
        admin,
        db_session,
    )

    admin_api.update_integration(
        integration_id,
        IntegrationUpdate(
            config=OpenApiConfigInput(
                base_url=BASE_URL,
                endpoints=[
                    # Kept as it was.
                    "POST /tickets Create a ticket",
                    # Renamed.
                    "GET /tickets/{id} Show one ticket",
                    # The method changed: a new operation.
                    "PATCH /tickets/{id} Update a ticket",
                    # New. The removed lines are GET /tickets and DELETE.
                    "GET /users List users",
                ],
            )
        ),
        admin,
        db_session,
    )

    view = _view(db_session, admin, integration_id)
    with pytest.raises(json.JSONDecodeError):
        json.loads(view.openapi_document)
    spec = yaml.safe_load(view.openapi_document)
    assert spec["info"] == IMPORTED["info"]
    assert spec["servers"] == [{"url": BASE_URL}]
    operations = _operations(view.openapi_document)
    assert set(operations) == {
        "createTicket",
        "getTicket",
        "patch_tickets_id",
        "get_users",
    }
    assert operations["createTicket"] == IMPORTED["paths"]["/tickets"]["post"]
    assert operations["getTicket"] == {
        **IMPORTED["paths"]["/tickets/{id}"]["get"],
        "summary": "Show one ticket",
    }
    assert operations["patch_tickets_id"]["summary"] == "Update a ticket"

    actions = {
        action.key: action
        for action in admin_api.get_integration_actions(
            integration_id, admin, db_session
        ).actions
    }
    assert set(actions) == set(operations)
    assert actions["createTicket"].admin_policy is EffectivePolicy.BLOCKED
    assert actions["getTicket"].admin_policy is EffectivePolicy.ASK
    assert actions["getTicket"].display_name == "Show one ticket"
    assert actions["patch_tickets_id"].admin_policy is None


def test_unchanged_lines_keep_the_document_text(
    db_session: Session, admin: User, created: list[int]
) -> None:
    document = "# Kept\n" + yaml.safe_dump(
        {**IMPORTED, "servers": [{"url": BASE_URL}]}, sort_keys=False
    )
    integration_id = _create(
        db_session, admin, created, OpenApiConfigInput(openapi_document=document)
    )
    view = _view(db_session, admin, integration_id)
    admin_api.update_integration(
        integration_id,
        IntegrationUpdate(
            config=OpenApiConfigInput(base_url=BASE_URL, endpoints=view.endpoints)
        ),
        admin,
        db_session,
    )
    assert _view(db_session, admin, integration_id).openapi_document == document


def test_each_bad_line_gets_its_own_error(
    db_session: Session, admin: User, created: list[int]
) -> None:
    integration_id = _create(
        db_session,
        admin,
        created,
        OpenApiConfigInput(base_url=BASE_URL, endpoints=["GET /tickets List"]),
    )
    with pytest.raises(OnyxError) as error:
        admin_api.update_integration(
            integration_id,
            IntegrationUpdate(
                config=OpenApiConfigInput(
                    base_url=BASE_URL,
                    endpoints=[
                        "GET /tickets List",
                        "FETCH /tickets List",
                        "GET tickets List",
                        "GET /tickets/{id",
                        "GET /tickets Again",
                        "GET /a-b One",
                        "GET /a_b Two",
                        "GET /search?q=1 Search",
                    ],
                )
            ),
            admin,
            db_session,
        )
    db_session.rollback()
    assert error.value.error_code is OnyxErrorCode.VALIDATION_ERROR
    assert error.value.extra is not None
    line_errors = error.value.extra["line_errors"]
    assert isinstance(line_errors, list)
    assert [
        EndpointLineError.model_validate(line_error).line for line_error in line_errors
    ] == [1, 2, 3, 4, 5, 6, 7]
    assert _view(db_session, admin, integration_id).endpoints == ["GET /tickets List"]
