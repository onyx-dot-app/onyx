"""The readers of an OpenAPI integration's definition read the ``api_app``
row, not the ``tool`` row that the dual write also keeps."""

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationAuthMode, PluginInstallationPolicy
from onyx.db.integration import list_integration_actions
from onyx.db.models import ApiApp, Integration, Tool, User
from onyx.integrations.chat_tools import build_integration_chat_tools
from onyx.integrations.kinds.api import sync_integration_actions__no_commit
from onyx.integrations.models import ActionSettings, ApprovalMode
from onyx.sandbox_proxy.usable_integrations import load_match_targets
from onyx.server.features.integrations import admin_api
from onyx.server.features.integrations.models import (
    IntegrationCreate,
    OpenApiConfigInput,
    OpenApiConfigView,
)
from onyx.server.features.tool import api as tool_api
from onyx.tools.models import IntegrationChatRequest, IntegrationLinkConfiguration
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    parse_openapi_document,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
)


def _spec(host: str, operation_id: str) -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Items", "description": "Items", "version": "1.0"},
        "servers": [{"url": f"https://{host}/v1"}],
        "paths": {"/items": {"get": {"operationId": operation_id, "summary": "List"}}},
    }


API_APP_SPEC = _spec("api-app.example.com", "list_from_api_app")
TOOL_ROW_SPEC = _spec("tool-row.example.com", "list_from_tool_row")


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("api-app-reads-admin", is_admin=True)


@pytest.fixture
def integration_ids(db_session: Session, admin: User) -> Iterator[list[int]]:  # noqa: ARG001
    ids: list[int] = []
    yield ids
    delete_integrations(db_session, ids)


@pytest.mark.parametrize("document_format", ["json", "yaml"])
def test_readers_use_the_api_app_document(
    db_session: Session, admin: User, integration_ids: list[int], document_format: str
) -> None:
    detail = admin_api.create_integration(
        IntegrationCreate(
            name=f"items-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.NONE,
            config=OpenApiConfigInput(openapi_document=json.dumps(API_APP_SPEC)),
        ),
        admin,
        db_session,
    )
    integration_ids.append(detail.id)
    integration = db_session.get(Integration, detail.id)
    assert integration is not None and integration.tool_id is not None
    tool_id = integration.tool_id
    db_session.execute(
        update(Tool).where(Tool.id == tool_id).values(openapi_schema=TOOL_ROW_SPEC)
    )
    if document_format == "yaml":
        db_session.execute(
            update(ApiApp)
            .where(ApiApp.id == integration.api_app_id)
            .values(openapi_document=yaml.safe_dump(API_APP_SPEC))
        )
    give_access(
        db_session, [integration], installation_policy=PluginInstallationPolicy.DEFAULT
    )
    db_session.commit()

    config = admin_api.get_integration_admin(detail.id, admin, db_session).config
    assert isinstance(config, OpenApiConfigView)
    assert parse_openapi_document(config.openapi_document) == API_APP_SPEC

    sync_integration_actions__no_commit(integration, db_session)
    db_session.commit()
    assert [
        action.key for action in list_integration_actions(detail.id, db_session)
    ] == ["list_from_api_app"]

    tools = build_integration_chat_tools(
        db_session,
        admin,
        IntegrationChatRequest(
            persona_id=7,
            integration_links=[
                IntegrationLinkConfiguration(
                    integration_id=detail.id, action_settings=ActionSettings()
                )
            ],
            approval_mode=ApprovalMode.INTERACTIVE,
        ),
    )
    assert len(tools) == 1
    assert isinstance(tools[0], CustomTool)
    assert tools[0].integration_action is not None
    assert tools[0].integration_action.action == "list_from_api_app"
    assert tools[0]._base_url == "https://api-app.example.com/v1"

    (target,) = load_match_targets(db_session, detail.id)
    assert target.load_error is None and target.endpoint is not None
    assert target.endpoint.host == "api-app.example.com"

    snapshot = tool_api.get_custom_tool(tool_id, db_session, admin)
    assert snapshot.definition == API_APP_SPEC
