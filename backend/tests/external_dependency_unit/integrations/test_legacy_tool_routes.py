"""Old ``/tool`` routes keep serving migrated MCP tool rows: a client that
holds a pre-integrations tool id must still see it in ``GET /tool`` and
``GET /tool/{id}``."""

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import Tool
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.tool.api import (
    get_custom_tool,
    list_tools,
    update_tool_user_preferences,
)
from onyx.server.features.tool.models import ToolUserPreferences
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.integration_helpers import (
    give_access,
    make_mcp_integration,
)


def _legacy_mcp_tool(db_session: Session) -> Tool:
    integration, server = make_mcp_integration(db_session)
    # The integrations migration keeps the MCP server's old ``tool`` rows.
    tool = Tool(
        name="legacy_mcp_action",
        description="Migrated MCP action",
        enabled=True,
        passthrough_auth=False,
        mcp_server_id=server.id,
    )
    db_session.add(tool)
    db_session.commit()
    give_access(db_session, [integration])
    return tool


def test_mcp_tool_in_list_and_detail(db_session: Session) -> None:
    user = create_test_user(db_session, "legacy-tools")
    tool = _legacy_mcp_tool(db_session)

    listed = list_tools(db_session=db_session, user=user)
    assert tool.id in [snapshot.id for snapshot in listed]

    snapshot = get_custom_tool(tool_id=tool.id, db_session=db_session, user=user)
    assert snapshot.mcp_server_id == tool.mcp_server_id


def test_mcp_tool_preferences_rejected_as_before(db_session: Session) -> None:
    user = create_test_user(db_session, "legacy-tool-prefs")
    tool = _legacy_mcp_tool(db_session)

    with pytest.raises(OnyxError) as exc:
        update_tool_user_preferences(
            tool_id=tool.id,
            request=ToolUserPreferences(enabled_in_chat=True),
            db_session=db_session,
            user=user,
        )
    assert exc.value.error_code is OnyxErrorCode.INVALID_INPUT
