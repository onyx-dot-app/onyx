"""For one release each write of an OpenAPI integration's tool row also writes
its api_app row, in the same transaction."""

import json
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ApiAppType, IntegrationAuthMethod, IntegrationAuthMode
from onyx.db.integration import get_openapi_tool_for_integration
from onyx.db.models import ApiApp, Integration, Tool, User
from onyx.server.features.integrations import admin_api
from onyx.server.features.integrations.models import (
    IntegrationCreate,
    IntegrationUpdate,
    OpenApiConfigInput,
)
from onyx.server.features.tool import api as tool_api
from onyx.server.features.tool.models import CustomToolCreate
from tests.external_dependency_unit.conftest import MakeTestUser


def _spec(server_url: str, operation_id: str) -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Weather", "description": "Weather", "version": "1.0"},
        "servers": [{"url": server_url}],
        "paths": {
            "/forecast": {"get": {"operationId": operation_id, "summary": "Get"}}
        },
    }


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("api-app-admin", is_admin=True)


def _api_app(db_session: Session, integration_id: int) -> ApiApp:
    db_session.expire_all()
    integration = db_session.get(Integration, integration_id)
    assert integration is not None and integration.api_app_id is not None
    app = db_session.get(ApiApp, integration.api_app_id)
    assert app is not None
    return app


def _assert_matches_tool(db_session: Session, integration_id: int) -> ApiApp:
    app = _api_app(db_session, integration_id)
    tool = get_openapi_tool_for_integration(integration_id, db_session)
    assert tool is not None and tool.openapi_schema is not None
    assert app.api_type is ApiAppType.REST
    assert app.openapi_document is not None
    assert json.loads(app.openapi_document) == tool.openapi_schema
    assert app.graphql_schema is None
    return app


def test_create_update_and_delete_write_the_api_app_row(
    db_session: Session, admin: User
) -> None:
    detail = admin_api.create_integration(
        IntegrationCreate(
            name=f"weather-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.SHARED,
            auth_method=IntegrationAuthMethod.API_KEY,
            header_template={"X-Api-Key": "{api_key}"},
            config=OpenApiConfigInput(
                openapi_spec=_spec("https://weather.example.com", "get_forecast")
            ),
        ),
        admin,
        db_session,
    )
    app = _assert_matches_tool(db_session, detail.id)
    assert app.base_url == "https://weather.example.com"
    app_id = app.id

    admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            config=OpenApiConfigInput(
                openapi_spec=_spec("https://v2.weather.example.com", "get_v2")
            )
        ),
        admin,
        db_session,
    )
    app = _assert_matches_tool(db_session, detail.id)
    assert app.id == app_id
    assert app.base_url == "https://v2.weather.example.com"

    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    tool_id = integration.tool_id
    admin_api.delete_integration(detail.id, admin, db_session)

    db_session.expire_all()
    assert db_session.get(Integration, detail.id) is None
    assert db_session.get(Tool, tool_id) is None
    assert db_session.get(ApiApp, app_id) is None


def test_a_spec_change_adds_the_row_that_older_code_did_not_write(
    db_session: Session, admin: User
) -> None:
    detail = admin_api.create_integration(
        IntegrationCreate(
            name=f"weather-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.NONE,
            config=OpenApiConfigInput(
                openapi_spec=_spec("https://weather.example.com", "get_forecast")
            ),
        ),
        admin,
        db_session,
    )
    try:
        integration = db_session.get(Integration, detail.id)
        assert integration is not None
        old_app = db_session.get(ApiApp, integration.api_app_id)
        integration.api_app_id = None
        db_session.delete(old_app)
        db_session.commit()

        admin_api.update_integration(
            detail.id,
            IntegrationUpdate(
                config=OpenApiConfigInput(
                    openapi_spec=_spec("https://v2.weather.example.com", "get_v2")
                )
            ),
            admin,
            db_session,
        )
        assert (
            _assert_matches_tool(db_session, detail.id).base_url
            == "https://v2.weather.example.com"
        )
    finally:
        admin_api.delete_integration(detail.id, admin, db_session)


def test_the_legacy_tool_route_writes_the_api_app_row(
    db_session: Session, admin: User
) -> None:
    snapshot = tool_api.create_custom_tool(
        CustomToolCreate(
            name=f"weather-{uuid4().hex[:8]}",
            description="Forecasts",
            definition=_spec("https://weather.example.com", "get_forecast"),
            custom_headers=None,
            passthrough_auth=False,
        ),
        db_session,
        admin,
    )
    assert snapshot.integration_id is not None
    app = _assert_matches_tool(db_session, snapshot.integration_id)
    assert app.base_url == "https://weather.example.com"

    tool_api.delete_custom_tool(snapshot.id, db_session, admin)
    db_session.expire_all()
    assert db_session.get(ApiApp, app.id) is None
