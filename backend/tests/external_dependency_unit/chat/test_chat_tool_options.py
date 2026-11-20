"""The tool options of a send narrow the built-in tools and the integration
actions that a chat offers, and name the preferred tool."""

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.chat_utils import create_chat_session_from_request
from onyx.db.models import ChatSession, Persona, User
from onyx.db.tools import get_builtin_tool
from onyx.llm.model_response import Delta
from onyx.server.features.tool.api import list_tools
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.tools.models import (
    ActionPreference,
    CapabilityEntry,
    IntegrationEntry,
    ToolOptions,
)
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_name import normalize_external_tool_name
from tests.external_dependency_unit.answer.stream_test_utils import final_answer
from tests.external_dependency_unit.code_mode_helpers import ChatLLM, send
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    link_persona,
    make_mcp_integration,
    make_openapi_integration,
)

SERVER = "acme"
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


class Agent:
    def __init__(
        self,
        persona: Persona,
        user: User,
        mcp_id: int,
        api_id: int,
        api_tool_id: int,
        open_url_id: int,
    ) -> None:
        self.persona = persona
        self.user = user
        self.mcp_id = mcp_id
        self.api_id = api_id
        self.open_url_id = open_url_id
        self.api_tool_id = api_tool_id
        self.hello = normalize_external_tool_name(f"mcp__{mcp_id}__{SERVER}__hello")
        self.bye = normalize_external_tool_name(f"mcp__{mcp_id}__{SERVER}__bye")
        self.list_orders = normalize_external_tool_name(f"custom__{api_id}__listOrders")
        self.create_order = normalize_external_tool_name(
            f"custom__{api_id}__createOrder"
        )


@pytest.fixture
def agent(
    db_session: Session, make_test_user: MakeTestUser
) -> Generator[Agent, None, None]:
    user = make_test_user("chat_tool_options")
    mcp, _ = make_mcp_integration(
        db_session,
        # Construction reads the synced actions; no test calls the server.
        server_url="http://127.0.0.1:9/mcp",
        name=SERVER,
        tools=("hello", "bye"),
    )
    api, api_tool = make_openapi_integration(db_session, openapi_schema=ORDERS_SPEC)
    give_access(db_session, [mcp, api])
    open_url = get_builtin_tool(db_session, OpenURLTool)
    web_search = get_builtin_tool(db_session, WebSearchTool)
    persona = Persona(
        name=f"Tool options agent {uuid4().hex[:8]}",
        description="Agent with built-in tools and two integrations",
        system_prompt="You are a helpful assistant",
        task_prompt="",
        tools=[open_url, web_search],
        document_sets=[],
        user_id=user.id,
        groups=[],
        is_listed=True,
        is_public=True,
        display_priority=None,
        starter_messages=None,
        deleted=False,
    )
    db_session.add(persona)
    db_session.commit()
    link_persona(db_session, persona.id, mcp.id)
    link_persona(db_session, persona.id, api.id)
    try:
        yield Agent(
            persona,
            user,
            mcp.id,
            api.id,
            api_tool.id,
            open_url.id,
        )
    finally:
        delete_integrations(db_session, [mcp.id, api.id])
        persona.deleted = True
        db_session.commit()


def _chat(db_session: Session, agent: Agent) -> ChatSession:
    return create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=agent.persona.id),
        user=agent.user,
        db_session=db_session,
    )


def _offered(
    db_session: Session, agent: Agent, options: ToolOptions | None
) -> dict[str, str]:
    """The tools of the first model request of a send, by name, with their
    descriptions."""
    llm = ChatLLM([Delta(content="Done.")])
    parts = send(
        _chat(db_session, agent).id,
        agent.user,
        llm,
        "Help me.",
        code_mode=False,
        tool_options=options,
    )
    assert final_answer(parts) == "Done."
    return {
        tool["function"]["name"]: tool["function"]["description"]
        for tool in llm.requests[0]["tools"]
    }


def test_without_options_the_chat_offers_each_action_of_each_integration(
    db_session: Session, agent: Agent
) -> None:
    offered = _offered(db_session, agent, None)
    assert {agent.hello, agent.bye, agent.list_orders, agent.create_order} <= set(
        offered
    )
    assert offered[OpenURLTool.NAME] == OpenURLTool.DESCRIPTION


def test_an_integration_entry_with_one_action_offers_only_that_action(
    db_session: Session, agent: Agent
) -> None:
    offered = _offered(
        db_session,
        agent,
        ToolOptions(
            allowed=[
                IntegrationEntry(integration_id=agent.api_id, actions=["listOrders"])
            ]
        ),
    )
    assert agent.list_orders in offered
    assert not {agent.hello, agent.bye, agent.create_order} & set(offered)
    # No capability entry: no built-in tool.
    assert OpenURLTool.NAME not in offered


def test_an_integration_that_is_not_allowed_offers_no_action(
    db_session: Session, agent: Agent
) -> None:
    offered = _offered(
        db_session,
        agent,
        ToolOptions(allowed=[CapabilityEntry(tool_id=agent.open_url_id)]),
    )
    assert OpenURLTool.NAME in offered
    assert not {
        agent.hello,
        agent.bye,
        agent.list_orders,
        agent.create_order,
    } & set(offered)


def test_open_url_does_not_fetch_from_the_web_when_web_search_is_not_allowed(
    db_session: Session, agent: Agent
) -> None:
    offered = _offered(
        db_session,
        agent,
        ToolOptions(
            allowed=[
                CapabilityEntry(tool_id=agent.open_url_id),
                IntegrationEntry(integration_id=agent.mcp_id),
                IntegrationEntry(integration_id=agent.api_id),
            ]
        ),
    )
    assert WebSearchTool.NAME not in offered
    assert offered[OpenURLTool.NAME] == OpenURLTool.DESCRIPTION_NO_WEB_FETCH
    assert {agent.hello, agent.bye, agent.list_orders, agent.create_order} <= set(
        offered
    )


def test_an_action_preference_reaches_the_agent(
    db_session: Session, agent: Agent
) -> None:
    llm = ChatLLM([Delta(content="Done.")])
    send(
        _chat(db_session, agent).id,
        agent.user,
        llm,
        "Help me.",
        code_mode=False,
        tool_options=ToolOptions(
            preferred=ActionPreference(integration_id=agent.api_id, action="listOrders")
        ),
    )
    prompt_text = "\n".join(
        str(message.content) for message in llm.requests[0]["prompt"]
    )
    assert (
        f"The user selected these operations for this request: {agent.list_orders}."
        in prompt_text
    )


def test_the_catalog_names_the_integration_of_each_tool(
    db_session: Session, agent: Agent
) -> None:
    tools = list_tools(db_session=db_session, user=agent.user)
    assert [
        (tool.integration_id, tool.plugin_ids)
        for tool in tools
        if tool.id == agent.api_tool_id
    ] == [(agent.api_id, [str(agent.api_id)])]


def test_a_plugin_entry_of_the_mobile_app_names_the_integration(
    db_session: Session, agent: Agent
) -> None:
    """The released mobile app sends each ``plugin_ids`` value of the tool
    list back in a ``plugin`` entry."""
    options = ToolOptions.model_validate(
        {
            "allowed": [
                {"type": "plugin", "plugin_id": str(agent.api_id)},
                {"type": "plugin", "plugin_id": str(uuid4())},
            ]
        }
    )
    assert options.allowed == [IntegrationEntry(integration_id=agent.api_id)]
    offered = _offered(db_session, agent, options)
    assert {agent.list_orders, agent.create_order} <= set(offered)
    assert not {agent.hello, agent.bye} & set(offered)
