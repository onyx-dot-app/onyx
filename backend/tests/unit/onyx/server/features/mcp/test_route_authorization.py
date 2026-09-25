from collections.abc import Generator
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db import mcp as mcp_db
from onyx.db.enums import MCPAuthenticationPerformer, MCPAuthenticationType
from onyx.db.models import MCPServer, Tool, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api
from onyx.server.features.mcp.models import (
    MCPAuthTemplate,
    MCPToolCreateRequest,
    MCPUserCredentialsRequest,
)
from onyx.server.features.tool import api as tool_api
from onyx.server.features.tool.models import CustomToolCreate, CustomToolUpdate, Header
from onyx.utils.encryption import mask_string


@pytest.fixture
def user() -> User:
    return User(id=uuid4(), email="user@example.com", is_group_manager=True)


@pytest.fixture
def db() -> MagicMock:
    return MagicMock(spec=Session)


@pytest.fixture
def server() -> Generator[MCPServer, None, None]:
    server = MCPServer(
        id=1,
        name="Example",
        server_url="https://example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
    )
    with (
        patch.object(api, "get_mcp_server_by_id", return_value=server),
        patch.object(mcp_db, "user_can_access_mcp_server", return_value=True),
        patch.object(mcp_db, "can_manage_mcp_server", return_value=False),
        patch.object(api, "_hot_reload_craft_sessions"),
        patch.object(api, "resolve_mcp_credentials") as resolve,
    ):
        resolve.return_value.can_authenticate.return_value = True
        yield server


def credentials() -> MCPUserCredentialsRequest:
    return MCPUserCredentialsRequest(
        server_id=1,
        credentials={"api_key": "test-value", "user_email": "other@example.com"},
        transport="streamable-http",
    )


@pytest.mark.parametrize("operation", ["create", "enable", "repoint"])
def test_scoped_manager_cannot_configure_tool_passthrough(
    operation: str, user: User, db: MagicMock
) -> None:
    existing = Tool(id=1, passthrough_auth=operation != "enable")
    with (
        patch.object(tool_api, "_validate_tool_definition"),
        patch.object(tool_api, "_get_manageable_custom_tool", return_value=existing),
        patch.object(tool_api, "_assert_can_link_oauth_config"),
        patch.object(tool_api, "create_tool__no_commit"),
        patch.object(tool_api, "update_tool"),
        patch.object(tool_api.ToolSnapshot, "from_model"),
        pytest.raises(OnyxError) as error,
    ):
        if operation == "create":
            tool_api.create_custom_tool(
                CustomToolCreate(name="Example", definition={}, passthrough_auth=True),
                db,
                user,
            )
        else:
            update = (
                CustomToolUpdate(passthrough_auth=True)
                if operation == "enable"
                else CustomToolUpdate(
                    definition={"servers": [{"url": "https://example.com"}]}
                )
            )
            tool_api.update_custom_tool(1, update, db, user)
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db.commit.assert_not_called()


@pytest.mark.parametrize("existing_server_id", [None, 1])
def test_scoped_manager_cannot_configure_mcp_passthrough(
    existing_server_id: int | None, user: User, db: MagicMock
) -> None:
    request = MCPToolCreateRequest(
        name="Example",
        server_url="https://example.com/mcp",
        auth_type=MCPAuthenticationType.PT_OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        existing_server_id=existing_server_id,
    )
    with (
        patch.object(api, "_upsert_mcp_server") as upsert,
        patch.object(api, "MCPServerCreateResponse"),
    ):
        with pytest.raises(OnyxError) as error:
            api.upsert_mcp_server(request, db, user)
        assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        upsert.assert_not_called()


def test_hidden_persona_cannot_list_servers(user: User, db: MagicMock) -> None:
    with (
        patch.object(api, "get_persona_by_id", side_effect=ValueError, create=True),
        patch.object(api, "get_mcp_servers_for_persona", return_value=[]) as listing,
        pytest.raises(OnyxError) as error,
    ):
        api.get_mcp_servers_for_assistant("1", db, user)
    assert error.value.error_code == OnyxErrorCode.PERSONA_NOT_FOUND
    listing.assert_not_called()


@pytest.mark.parametrize("operation", ["save", "delete"])
def test_hidden_server_cannot_change_credentials(
    operation: str, server: MCPServer, user: User, db: MagicMock
) -> None:
    with (
        patch.object(mcp_db, "user_can_access_mcp_server", return_value=False),
        patch.object(api, "get_mcp_auth_template", return_value=None),
        patch.object(
            api, "test_mcp_server_credentials", return_value=(True, "OK")
        ) as probe,
        patch.object(api, "upsert_user_connection_config") as save,
        patch.object(api, "delete_user_connection_configs_for_server") as delete,
        pytest.raises(OnyxError) as error,
    ):
        if operation == "save":
            api.save_user_credentials(credentials(), db, user)
        else:
            api.delete_user_credentials(server.id, db, user)
    assert error.value.error_code == OnyxErrorCode.NOT_FOUND
    probe.assert_not_called()
    save.assert_not_called()
    delete.assert_not_called()


def test_render_uses_authenticated_email() -> None:
    template = MCPAuthTemplate(headers={"X-User": "{user_email}", "X-Key": "{api_key}"})
    assert template.render(
        credentials().credentials, user_email="user@example.com"
    ) == {
        "X-User": "user@example.com",
        "X-Key": "test-value",
    }


@pytest.mark.usefixtures("server")
def test_save_excludes_reserved_substitutions(user: User, db: MagicMock) -> None:
    with (
        patch.object(api, "get_mcp_auth_template", return_value=None),
        patch.object(api, "test_mcp_server_credentials", return_value=(True, "OK")),
        patch.object(api, "upsert_user_connection_config") as save,
    ):
        response = api.save_user_credentials(credentials(), db, user)
    assert response.success
    assert save.call_args.kwargs["config_data"]["header_substitutions"] == {
        "api_key": "test-value"
    }


def test_validation_error_hides_server_details(
    server: MCPServer, user: User, db: MagicMock
) -> None:
    with (
        patch.object(api, "get_mcp_auth_template", return_value=None),
        patch.object(
            api, "test_mcp_server_credentials", return_value=(False, server.server_url)
        ),
        pytest.raises(OnyxError) as error,
    ):
        api.save_user_credentials(credentials(), db, user)
    assert error.value.detail == "Credentials validation failed."
    db.commit.assert_not_called()


def _tool_definition() -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Example", "description": "Example action"},
        "servers": [{"url": "https://example.com"}],
        "paths": {"/items": {"get": {"operationId": "items", "summary": "List items"}}},
    }


@pytest.mark.parametrize("edit", ["unchanged", "metadata", "query_parameter"])
def test_scoped_manager_can_save_nonredirecting_passthrough_action(
    edit: str, user: User, db: MagicMock
) -> None:
    original = _tool_definition()
    updated = deepcopy(original)
    if edit == "metadata":
        updated["info"]["description"] = "Updated action"
        updated["paths"]["/items"]["get"]["summary"] = "Updated summary"
    elif edit == "query_parameter":
        updated["paths"]["/items"]["get"]["parameters"] = [
            {"name": "limit", "in": "query", "schema": {"type": "integer"}}
        ]
    existing = Tool(id=1, passthrough_auth=True, openapi_schema=original)
    with (
        patch.object(tool_api, "_get_manageable_custom_tool", return_value=existing),
        patch.object(tool_api, "_assert_can_link_oauth_config"),
        patch.object(tool_api, "update_tool") as update,
        patch.object(tool_api.ToolSnapshot, "from_model"),
    ):
        tool_api.update_custom_tool(
            1, CustomToolUpdate(definition=updated, passthrough_auth=True), db, user
        )
    assert update.call_args.kwargs["openapi_schema"] == updated


@pytest.mark.parametrize("edit", ["root_server", "path", "host_parameter"])
def test_scoped_manager_cannot_change_passthrough_destination(
    edit: str, user: User, db: MagicMock
) -> None:
    original = _tool_definition()
    if edit == "host_parameter":
        original["servers"] = [{"url": "https://{host}"}]
    updated = deepcopy(original)
    if edit == "root_server":
        updated["servers"] = [{"url": "https://other.example.com"}]
    elif edit == "path":
        updated["paths"]["/other"] = updated["paths"].pop("/items")
    else:
        updated["paths"]["/items"]["get"]["parameters"] = [
            {"name": "host", "in": "path", "schema": {"type": "string"}}
        ]
    existing = Tool(id=1, passthrough_auth=True, openapi_schema=original)
    with (
        patch.object(tool_api, "_get_manageable_custom_tool", return_value=existing),
        patch.object(tool_api, "_assert_can_link_oauth_config"),
        patch.object(tool_api, "update_tool") as update,
        patch.object(tool_api.ToolSnapshot, "from_model"),
        pytest.raises(OnyxError) as error,
    ):
        tool_api.update_custom_tool(1, CustomToolUpdate(definition=updated), db, user)
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    update.assert_not_called()


@pytest.mark.parametrize("header_name", ["Host", "hOsT"])
def test_scoped_manager_cannot_change_passthrough_headers(
    header_name: str, user: User, db: MagicMock
) -> None:
    definition = _tool_definition()
    existing = Tool(id=1, passthrough_auth=True, openapi_schema=definition)
    with (
        patch.object(tool_api, "_get_manageable_custom_tool", return_value=existing),
        patch.object(tool_api, "_assert_can_link_oauth_config"),
        patch.object(tool_api, "update_tool") as update,
        patch.object(tool_api.ToolSnapshot, "from_model"),
        pytest.raises(OnyxError) as error,
    ):
        tool_api.update_custom_tool(
            1,
            CustomToolUpdate(
                definition=definition,
                passthrough_auth=True,
                custom_headers=[Header(key=header_name, value="other.example.com")],
            ),
            db,
            user,
        )
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    update.assert_not_called()


def test_scoped_manager_can_preserve_masked_passthrough_headers(
    user: User, db: MagicMock
) -> None:
    definition = _tool_definition()
    existing = Tool(
        id=1,
        passthrough_auth=True,
        openapi_schema=definition,
        custom_headers=[{"key": "Host", "value": "example.com"}],
    )
    with (
        patch.object(tool_api, "_get_manageable_custom_tool", return_value=existing),
        patch.object(tool_api, "_assert_can_link_oauth_config"),
        patch.object(tool_api, "update_tool") as update,
        patch.object(tool_api.ToolSnapshot, "from_model"),
    ):
        tool_api.update_custom_tool(
            1,
            CustomToolUpdate(
                definition=definition,
                passthrough_auth=True,
                custom_headers=[Header(key="Host", value=mask_string("example.com"))],
            ),
            db,
            user,
        )
    assert update.call_args.kwargs["custom_headers"] == [
        Header(key="Host", value="example.com")
    ]


def test_scoped_manager_cannot_relax_passthrough_host_constraints(
    user: User, db: MagicMock
) -> None:
    original = _tool_definition()
    original["servers"] = [{"url": "https://{host}"}]
    original["paths"]["/items"]["get"]["parameters"] = [
        {
            "name": "host",
            "in": "path",
            "schema": {"type": "string", "enum": ["example.com"]},
        }
    ]
    updated = deepcopy(original)
    del updated["paths"]["/items"]["get"]["parameters"][0]["schema"]["enum"]
    existing = Tool(id=1, passthrough_auth=True, openapi_schema=original)
    with (
        patch.object(tool_api, "_get_manageable_custom_tool", return_value=existing),
        patch.object(tool_api, "_assert_can_link_oauth_config"),
        patch.object(tool_api, "update_tool") as update,
        patch.object(tool_api.ToolSnapshot, "from_model"),
        pytest.raises(OnyxError) as error,
    ):
        tool_api.update_custom_tool(1, CustomToolUpdate(definition=updated), db, user)
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    update.assert_not_called()


def test_empty_definition_returns_client_error(user: User, db: MagicMock) -> None:
    existing = Tool(id=1, passthrough_auth=True, openapi_schema=_tool_definition())
    with (
        patch.object(tool_api, "_get_manageable_custom_tool", return_value=existing),
        pytest.raises(OnyxError) as error,
    ):
        tool_api.update_custom_tool(1, CustomToolUpdate(definition={}), db, user)
    assert error.value.status_code == 400
    assert error.value.error_code == OnyxErrorCode.VALIDATION_ERROR


def test_unexpected_validator_failure_propagates(user: User, db: MagicMock) -> None:
    existing = Tool(id=1, passthrough_auth=True, openapi_schema=_tool_definition())
    with (
        patch.object(tool_api, "_get_manageable_custom_tool", return_value=existing),
        patch.object(
            tool_api,
            "validate_openapi_schema",
            side_effect=RuntimeError("validator failed"),
        ),
        pytest.raises(RuntimeError, match="validator failed"),
    ):
        tool_api.update_custom_tool(
            1, CustomToolUpdate(definition=_tool_definition()), db, user
        )
