"""A chat calls the MCP and OpenAPI actions of its agent's integrations through the
integration tables, with code mode on and off. An Ask action waits for the
user's approval, keyed by its integration."""

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.chat.chat_utils import create_chat_session_from_request
from onyx.db.enums import IntegrationActionPolicyValue
from onyx.db.models import ApprovalRequest, Persona, User
from onyx.llm.model_response import Delta
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.streaming_models import (
    AWAITING_USER,
    OverallStop,
    Packet,
)
from onyx.tools.tool_name import normalize_external_tool_name
from tests.external_dependency_unit.answer.stream_test_utils import final_answer
from tests.external_dependency_unit.code_mode_helpers import (
    ChatLLM,
    code_step,
    last_tool_text,
    send,
    tool_step,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    link_persona,
    make_mcp_integration,
    make_openapi_integration,
    set_policy,
)
from tests.external_dependency_unit.tools.test_code_mode import (  # noqa: F401
    mcp_server_url,
)

ALLOW = IntegrationActionPolicyValue.ALLOW
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
    def __init__(self, persona: Persona, mcp_id: int, api_id: int) -> None:
        self.persona = persona
        self.mcp_id = mcp_id
        self.api_id = api_id

    @property
    def hello(self) -> str:
        return normalize_external_tool_name(f"mcp__{self.mcp_id}__{SERVER}__hello")

    @property
    def list_orders(self) -> str:
        return normalize_external_tool_name(f"custom__{self.api_id}__listOrders")


@pytest.fixture
def agent(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,  # noqa: F811
) -> Generator[tuple[Agent, User], None, None]:
    user = make_test_user("integration_chat_actions")
    mcp, _ = make_mcp_integration(
        db_session,
        server_url=mcp_server_url,
        name=SERVER,
        tools=("hello",),
        description="Say hi.",
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
    )
    api, _ = make_openapi_integration(db_session, openapi_schema=ORDERS_SPEC)
    ids = [mcp.id, api.id]
    give_access(db_session, [mcp, api])
    persona = Persona(
        name=f"Integration agent {uuid4().hex[:8]}",
        description="Agent with integrations",
        system_prompt="You are a helpful assistant",
        task_prompt="",
        tools=[],
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
        yield Agent(persona, mcp.id, api.id), user
    finally:
        delete_integrations(db_session, ids)


def _chat(db_session: Session, agent: Agent, user: User) -> Any:
    return create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=agent.persona.id),
        user=user,
        db_session=db_session,
    )


def _orders_response(
    sent: list[dict[str, str]],
) -> Any:
    def respond(*_args: Any, **kwargs: Any) -> requests.Response:
        sent.append(dict(kwargs.get("headers") or {}))
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps({"orders": ["A-1"]}).encode()
        return response

    return respond


@pytest.mark.parametrize("code_mode", [False, True])
def test_a_chat_calls_an_mcp_action(
    db_session: Session, agent: tuple[Agent, User], code_mode: bool
) -> None:
    integration_agent, user = agent
    set_policy(db_session, integration_agent.mcp_id, "hello", ALLOW)
    chat = _chat(db_session, integration_agent, user)
    first = (
        code_step(
            "call",
            f"r = await tools.{integration_agent.hello}(name='alpha')\nprint(r['result'])\n",
        )
        if code_mode
        else tool_step(integration_agent.hello, "call", {"name": "alpha"})
    )
    llm = ChatLLM([first, Delta(content="Greeted.")])

    parts = send(chat.id, user, llm, "Greet alpha.", code_mode=code_mode)

    assert final_answer(parts) == "Greeted."
    assert "Hello, alpha!" in last_tool_text(llm, "call")


@pytest.mark.parametrize("code_mode", [False, True])
def test_a_chat_calls_an_openapi_action(
    db_session: Session, agent: tuple[Agent, User], code_mode: bool
) -> None:
    integration_agent, user = agent
    chat = _chat(db_session, integration_agent, user)
    first = (
        code_step(
            "call",
            f"r = await tools.{integration_agent.list_orders}()\nprint(r)\n",
        )
        if code_mode
        else tool_step(integration_agent.list_orders, "call", {})
    )
    llm = ChatLLM([first, Delta(content="Listed.")])
    sent: list[dict[str, str]] = []

    with patch(
        "onyx.tools.tool_implementations.custom.custom_tool.ssrf_safe_request",
        side_effect=_orders_response(sent),
    ):
        parts = send(chat.id, user, llm, "List orders.", code_mode=code_mode)

    assert final_answer(parts) == "Listed."
    assert "A-1" in last_tool_text(llm, "call")
    assert len(sent) == 1


def test_an_ask_action_in_a_program_opens_one_request(
    db_session: Session, agent: tuple[Agent, User]
) -> None:
    integration_agent, user = agent
    chat = _chat(db_session, integration_agent, user)
    llm = ChatLLM(
        [
            code_step(
                "call",
                f"r = await tools.{integration_agent.hello}(name='alpha')\nprint(r)\n",
            )
        ]
    )

    parts = send(chat.id, user, llm, "Greet alpha.")

    stops = [
        part.obj
        for part in parts
        if isinstance(part, Packet) and isinstance(part.obj, OverallStop)
    ]
    assert [stop.stop_reason for stop in stops] == [AWAITING_USER]
    db_session.expire_all()
    rows = list(
        db_session.scalars(
            select(ApprovalRequest).where(ApprovalRequest.chat_session_id == chat.id)
        )
    )
    assert [(row.integration_id, row.action_id) for row in rows] == [
        (integration_agent.mcp_id, "hello")
    ]
    assert rows[0].gated_app_id is None
