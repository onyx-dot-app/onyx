"""Each tool family gets the tool names and arguments that its models are
trained on, over the same operations, and a chat keeps the calls of both
families: agents, skills and web pages through the real server."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import aliased
from tenacity import (
    RetryError,
    Retrying,
    retry_if_result,
    stop_before_delay,
    wait_fixed,
)

from onyx.configs.chat_configs import CODE_MODE_ENABLED
from onyx.configs.constants import MessageType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage, ChatSession
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import ChatSessionDetailResponse
from onyx.skills.bundle import build_skill_md
from onyx.tools.tool_implementations.code_mode.shapes import CLAUDE_CODE_MODE
from onyx.tools.tool_implementations.subagents.shapes import AGENT_SHAPES
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import (
    CLAUDE_MOCK_LLM_MODEL_NAME,
    MOCK_LLM_MODEL_NAME,
    MockLLMScript,
    tool_call_reply,
)
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    RecordedRequest,
    Reply,
    RequestConditions,
    ToolCall,
)

WAIT_TIMEOUT_S = 60
NO_AGENT = "No agent on this chat branch has the path '/root/nobody'"


def _wait_until(condition: Callable[[], bool], description: str) -> None:
    poll = Retrying(
        retry=retry_if_result(lambda met: not met),
        stop=stop_before_delay(WAIT_TIMEOUT_S),
        wait=wait_fixed(0.2),
    )
    try:
        poll(condition)
    except RetryError as error:
        raise AssertionError(f"Timed out waiting until {description}") from error


def _detail(session_id: UUID, user: DATestUser) -> ChatSessionDetailResponse:
    response = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{session_id}",
        headers=user.headers,
    )
    response.raise_for_status()
    return ChatSessionDetailResponse.model_validate(response.json())


def _answered(session_id: UUID, user: DATestUser, text: str) -> Callable[[], bool]:
    def answered() -> bool:
        # Reading the status dispatches work that waits, as clients poll it.
        client.get(
            f"{API_SERVER_URL}/chat/chat-session/{session_id}/status",
            headers=user.headers,
        ).raise_for_status()
        detail = _detail(session_id, user)
        return not detail.is_processing and any(
            message.message == text
            for message in detail.messages
            if message.message_type == MessageType.ASSISTANT
        )

    return answered


def _use_model(session_id: UUID, provider: DATestLLMProvider, user: DATestUser) -> None:
    """Make the provider's model the chat's model: turns that the server
    starts, such as an agent result's follow-up, use it."""
    client.put(
        f"{API_SERVER_URL}/chat/update-chat-session-model",
        json={
            "chat_session_id": str(session_id),
            "new_alternate_model": f"{provider.name}__{provider.provider}__"
            f"{CLAUDE_MOCK_LLM_MODEL_NAME}__mc:{provider.model_configuration_ids[0]}",
        },
        headers=user.headers,
    ).raise_for_status()


def _definitions(request: RecordedRequest) -> dict[str, dict[str, Any]]:
    return {
        tool["function"]["name"]: tool["function"] for tool in request.body["tools"]
    }


def _arguments(definitions: dict[str, dict[str, Any]], name: str) -> set[str]:
    return set(definitions[name]["parameters"]["properties"])


def test_each_family_calls_agents_skills_and_pages_by_its_own_shape(
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    claude_mock_llm: DATestLLMProvider,
) -> None:
    """A chat answers with the default model, then with a Claude model. Each
    turn starts an agent, messages a missing agent and reads a skill with
    its family's tools; each agent's result starts a follow-up, also in the
    Claude shape, which has no wait tool. A reload replays the
    calls of both shapes without the agents' runs."""
    nonce = uuid4().hex
    first_task = f"Research the first topic. {uuid4().hex}"
    second_task = f"Review the second topic. {uuid4().hex}"
    first_result = f"First agent result {uuid4().hex}"
    second_result = f"Second agent result {uuid4().hex}"
    instructions = f"Group the notes by area. Marker {uuid4().hex}."
    skill = SkillManager.create_from_editor(
        admin_user,
        name=f"shape-skill-{uuid4().hex[:8]}",
        description="Write release notes.",
        instructions_markdown=instructions,
    )
    skill_md = build_skill_md(
        name=skill.name,
        description="Write release notes.",
        instructions_markdown=instructions,
    )
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[
                ToolCall(
                    id="spawn-first",
                    name="spawn_agent",
                    arguments={"task_name": "research", "message": first_task},
                ),
                ToolCall(
                    id="send-first",
                    name="send_message",
                    arguments={"target": "/root/nobody", "message": "Hello."},
                ),
            ],
            conditions=RequestConditions(
                offers=["spawn_agent", "send_message", "wait_agent"],
                does_not_offer=["agent", "skill", "web_fetch"],
            ),
        ),
        tool_call_reply(
            ToolCall(
                id="read-first", name="skills_read", arguments={"name": skill.name}
            ),
            conditions=RequestConditions(has_results_for=["spawn-first"]),
        ),
        Reply(
            text="Started the first agent.",
            conditions=RequestConditions(has_results_for=["read-first"]),
        ),
        Reply(
            text="The first agent finished.",
            conditions=RequestConditions(prompt_contains=[first_result]),
        ),
        Reply(
            tool_calls=[
                ToolCall(
                    id="spawn-second",
                    name="agent",
                    arguments={"description": "review", "prompt": second_task},
                ),
                ToolCall(
                    id="send-second",
                    name="send_message",
                    arguments={"to": "/root/nobody", "message": "Hello."},
                ),
            ],
            conditions=RequestConditions(
                offers=["agent", "send_message"],
                does_not_offer=["spawn_agent", "wait_agent", "skills_read", "open_url"],
            ),
        ),
        tool_call_reply(
            ToolCall(id="read-second", name="skill", arguments={"skill": skill.name}),
            conditions=RequestConditions(has_results_for=["spawn-second"]),
            shape=CLAUDE_CODE_MODE,
        ),
        Reply(
            text="Started the second agent.",
            conditions=RequestConditions(has_results_for=["read-second"]),
        ),
        Reply(
            text="The second agent finished.",
            conditions=RequestConditions(prompt_contains=[second_result]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    mock_llm.conversation(
        first_task,
        Reply(text=first_result, pause_after_first_chunk=first_task),
        conditions=RequestConditions(prompt_contains=[first_task]),
    )
    mock_llm.conversation(
        second_task,
        Reply(text=second_result, pause_after_first_chunk=second_task),
        conditions=RequestConditions(prompt_contains=[second_task]),
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    try:
        first = ChatSessionManager.send_message(
            session.id,
            f"Start the first agent. {nonce}",
            admin_user,
            accepts_follow_ups=True,
        )
        assert first.error is None, first.error
        assert first.full_message == "Started the first agent."
        # The agent answers once the root's turn ended.
        mock_llm.release_gate(first_task)
        _wait_until(
            _answered(session.id, admin_user, "The first agent finished."),
            "the first agent's result is answered",
        )
        # The second agent's follow-up uses the chat's model.
        _use_model(session.id, claude_mock_llm, admin_user)
        second = ChatSessionManager.send_message(
            session.id,
            f"Start the second agent. {nonce}",
            admin_user,
            llm_override=LLMOverride(
                model_configuration_id=claude_mock_llm.model_configuration_ids[0]
            ),
            accepts_follow_ups=True,
        )
        assert second.error is None, second.error
        assert second.full_message == "Started the second agent."
        mock_llm.release_gate(second_task)
        _wait_until(
            _answered(session.id, admin_user, "The second agent finished."),
            "the second agent's result is answered",
        )
        packets = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{session.id}",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        )
        packets.raise_for_status()
        replayed_packets = packets.json()["packets"]
        replayed = str(replayed_packets)
    finally:
        mock_llm.release_gate(first_task)
        mock_llm.release_gate(second_task)
        assert ChatSessionManager.delete(session, admin_user)
        SkillManager.delete_custom(skill, admin_user)

    requests = mock_llm.requests_in(nonce)
    assert [request.body["model"] for request in requests] == [
        *[MOCK_LLM_MODEL_NAME] * 4,
        *[CLAUDE_MOCK_LLM_MODEL_NAME] * 4,
    ]
    openai_request, claude_request = requests[0], requests[4]
    openai_tools = _definitions(openai_request)
    claude_tools = _definitions(claude_request)

    # Agents: each family's names and arguments; only the default family
    # has a wait tool, and only its root prompt names one.
    assert _arguments(openai_tools, "spawn_agent") == {"task_name", "message"}
    assert _arguments(openai_tools, "send_message") == {"target", "message", "delivery"}
    assert _arguments(openai_tools, "wait_agent") == {"targets"}
    assert _arguments(claude_tools, "agent") == {"description", "prompt"}
    assert _arguments(claude_tools, "send_message") == {"to", "message", "delivery"}
    assert "Call `wait_agent` to wait for them." in openai_request.prompt_text
    assert "wait_agent" not in claude_request.prompt_text
    assert "End your response to wait" in claude_request.prompt_text
    # The agents got their tasks, and messages reach agents by each
    # family's argument.
    assert [request.prompt_text for request in mock_llm.requests_in(first_task)]
    assert [request.prompt_text for request in mock_llm.requests_in(second_task)]
    assert NO_AGENT in (requests[1].tool_result("send-first") or "")
    assert NO_AGENT in (requests[5].tool_result("send-second") or "")

    # Skills and pages: each family's names and arguments, as the model
    # calls them; in code mode, functions of the family's programs.
    if CODE_MODE_ENABLED:
        openai_program = openai_tools["exec"]["description"]
        claude_program = claude_tools["repl"]["description"]
        assert "async def skills_read(" in openai_program
        assert "async def open_url(" in openai_program
        assert "async def skill(" in claude_program
        assert "async def web_fetch(" in claude_program
        assert "async def skills_read(" not in claude_program
        assert "async def open_url(" not in claude_program
        assert "`tools.skills_read`" in openai_request.prompt_text
        assert "`tools.skill`" in claude_request.prompt_text
    else:
        assert _arguments(openai_tools, "skills_read") == {"name", "start_char"}
        assert _arguments(claude_tools, "skill") == {"skill", "start_char"}
        assert "open_url" in openai_tools and "web_fetch" not in openai_tools
        assert "web_fetch" in claude_tools and "open_url" not in claude_tools
        assert "`skills_read`" in openai_request.prompt_text
        assert "`skill`" in claude_request.prompt_text
    assert instructions in (requests[2].tool_result("read-first") or "")
    assert instructions in (requests[6].tool_result("read-second") or "")
    assert skill_md.splitlines()[-1] in (requests[6].tool_result("read-second") or "")

    # A reload replays both turns, with the card of each family's agent
    # start; the agents' runs show apart from the calls that started them.
    assert {"spawn_agent", "agent"} <= {
        packet["obj"]["tool_name"]
        for turn in replayed_packets
        for packet in turn
        if packet["obj"]["type"] == "custom_tool_start"
    }
    assert "Started the first agent." in replayed
    assert "Started the second agent." in replayed
    assert first_result not in replayed
    assert second_result not in replayed


def _finished_children(session_id: UUID) -> int:
    """The finished runs of the agents that the chat's root started."""
    spawner = aliased(ChatMessage)
    with get_session_with_current_tenant() as db_session:
        statuses = db_session.scalars(
            select(ChatMessage.response_status)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .join(spawner, spawner.id == ChatSession.spawned_by_message_id)
            .where(
                spawner.chat_session_id == session_id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        ).all()
    return sum(status is not None and status.is_terminal for status in statuses)


@pytest.mark.parametrize("family", list(ToolFamily))
def test_each_family_answers_each_result_of_its_agents_with_those_still_running(
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    mock_llm_of_family: Callable[[ToolFamily], DATestLLMProvider | None],
    family: ToolFamily,
) -> None:
    """A root that ends its response while its agents run, without a wait
    call (the Claude shape has no wait tool), answers each result as its agent
    finishes: three agents that finish at different times give three
    responses, and each result names the agents that still run."""
    nonce = uuid4().hex
    tasks = [f"Task {index}. {uuid4().hex}" for index in range(3)]
    results = [f"Result {index} {uuid4().hex}" for index in range(3)]
    shape = AGENT_SHAPES[family]
    spawn_arguments = (
        [
            {"description": f"worker{index}", "prompt": task}
            for index, task in enumerate(tasks)
        ]
        if family is ToolFamily.CLAUDE
        else [
            {"task_name": f"worker{index}", "message": task}
            for index, task in enumerate(tasks)
        ]
    )
    statuses = [
        '"still_running": ["/root/worker1", "/root/worker2"]',
        '"still_running": ["/root/worker2"]',
        '"still_running": []',
    ]
    follow_ups = [
        Reply(
            text=f"Agent {index} finished.",
            conditions=RequestConditions(
                prompt_contains=[*results[: index + 1], statuses[index]]
            ),
        )
        for index in range(3)
    ]
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[
                ToolCall(
                    id=f"spawn-{index}", name=shape.spawn_name, arguments=arguments
                )
                for index, arguments in enumerate(spawn_arguments)
            ]
        ),
        Reply(
            text="Started three agents.",
            conditions=RequestConditions(has_results_for=["spawn-0"]),
        ),
        *follow_ups,
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    for task, result in zip(tasks, results, strict=True):
        mock_llm.conversation(
            task,
            Reply(text=result, pause_after_first_chunk=task),
            conditions=RequestConditions(prompt_contains=[task]),
        )
    provider = mock_llm_of_family(family)
    session = ChatSessionManager.create(user_performing_action=admin_user)
    if provider is not None:
        # The follow-ups use the chat's model.
        _use_model(session.id, provider, admin_user)
    try:
        started = ChatSessionManager.send_message(
            session.id,
            f"Start three agents. {nonce}",
            admin_user,
            llm_override=None
            if provider is None
            else LLMOverride(
                model_configuration_id=provider.model_configuration_ids[0]
            ),
            accepts_follow_ups=True,
        )
        assert started.full_message == "Started three agents."
        for index, task in enumerate(tasks):
            mock_llm.release_gate(task)
            _wait_until(
                lambda finished=index + 1: _finished_children(session.id) >= finished,
                f"agent {index} finishes",
            )
            # A result that no wait holds starts a response at once.
            _wait_until(
                _answered(session.id, admin_user, f"Agent {index} finished."),
                f"the result of agent {index} is answered",
            )
        answers = [
            message.message
            for message in _detail(session.id, admin_user).messages
            if message.message_type == MessageType.ASSISTANT
        ]
    finally:
        for task in tasks:
            mock_llm.release_gate(task)
        assert ChatSessionManager.delete(session, admin_user)

    assert answers == [
        "Started three agents.",
        "Agent 0 finished.",
        "Agent 1 finished.",
        "Agent 2 finished.",
    ]
    # Every turn of the chat used the family's model, the follow-ups too.
    assert {request.body["model"] for request in mock_llm.requests_in(nonce)} == {
        MOCK_LLM_MODEL_NAME if provider is None else CLAUDE_MOCK_LLM_MODEL_NAME
    }
