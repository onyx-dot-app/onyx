"""OpenAPI availability follows persona selection, not a global kill switch."""

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.db.models import Tool, User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.tool import api
from onyx.server.features.tool.models import CustomToolCreate


def test_create_defaults_to_globally_available_and_rejects_disabled() -> None:
    payload = {"name": "Test API", "definition": {}, "passthrough_auth": False}
    assert CustomToolCreate.model_validate(payload).enabled is True
    assert CustomToolCreate.model_validate({**payload, "enabled": True}).enabled is True
    with pytest.raises(ValidationError, match="default Chat configuration"):
        CustomToolCreate.model_validate({**payload, "enabled": False})


@pytest.mark.parametrize("enabled", [True, False])
def test_global_status_batch_rejects_openapi_before_any_mutation(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    mcp = Tool(id=1, mcp_server_id=5, enabled=not enabled)
    openapi = Tool(id=2, openapi_schema={}, enabled=True)
    db = MagicMock(spec=Session)
    monkeypatch.setattr(api, "get_tools_by_ids", lambda *_: [mcp, openapi])
    monkeypatch.setattr(api, "can_manage_tool", lambda *_: True)
    with pytest.raises(OnyxError, match="default Chat configuration") as error:
        api.update_tools_status(
            api.ToolStatusUpdateRequest(tool_ids=[1, 2], enabled=enabled), db, User()
        )
    assert error.value.status_code == 400
    assert mcp.enabled is not enabled
    assert openapi.enabled is True
    db.commit.assert_not_called()


def test_global_status_still_updates_mcp_and_builtin_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = [
        Tool(id=1, mcp_server_id=5, openapi_schema={}, enabled=True),
        Tool(id=2, in_code_tool_id="search", openapi_schema={}, enabled=True),
    ]
    db = MagicMock(spec=Session)
    monkeypatch.setattr(api, "get_tools_by_ids", lambda *_: tools)
    monkeypatch.setattr(api, "can_manage_tool", lambda *_: True)
    response = api.update_tools_status(
        api.ToolStatusUpdateRequest(tool_ids=[1, 2], enabled=False), db, User()
    )
    assert response.updated_count == 2
    assert all(not tool.enabled for tool in tools)
    db.commit.assert_called_once()


@pytest.mark.parametrize("persona_id", [0, 7])
def test_legacy_disabled_openapi_is_available_only_to_custom_agents(
    persona_id: int,
) -> None:
    from onyx.server.features.tool.models import ToolSnapshot
    from onyx.server.features.tool.tool_visibility import is_tool_available_for_persona

    legacy = Tool(
        id=1,
        name="Legacy API",
        openapi_schema={},
        enabled=False,
        passthrough_auth=False,
    )
    assert is_tool_available_for_persona(legacy, persona_id) is (persona_id != 0)
    assert ToolSnapshot.from_model(legacy).enabled is True
    for other in [
        Tool(enabled=False),
        Tool(enabled=False, openapi_schema={}, mcp_server_id=1),
        Tool(enabled=False, openapi_schema={}, in_code_tool_id="search"),
    ]:
        assert not is_tool_available_for_persona(other, persona_id)


def test_default_configuration_omits_legacy_disabled_links_and_explicit_selection_enables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.db import persona as persona_db
    from onyx.db.models import Persona
    from onyx.server.features.default_assistant import api as default_api

    legacy = Tool(id=1, openapi_schema={}, enabled=False)
    active = Tool(id=2, openapi_schema={}, enabled=True)
    default = Persona(id=0, tools=[legacy, active], system_prompt=None)
    db = MagicMock(spec=Session)
    monkeypatch.setattr(default_api, "get_default_assistant", lambda *_: default)
    monkeypatch.setattr(persona_db, "get_default_assistant", lambda *_: default)
    tools = {1: legacy, 2: active}
    db.query.return_value.filter.return_value.one_or_none.side_effect = [
        active,
        legacy,
        active,
    ]
    before = default_api.get_default_assistant_configuration(User(), db)
    assert before.tool_ids == [2]
    # A read-modify-write of another setting must not activate stale attachments.
    persona_db.update_default_assistant_configuration(db, tool_ids=before.tool_ids)
    assert legacy.enabled is False
    assert default.tools == [active]
    persona_db.update_default_assistant_configuration(db, tool_ids=[1, 2])
    assert legacy.enabled is True
    assert default.tools == [tools[1], tools[2]]
    assert db.commit.call_count == 2
