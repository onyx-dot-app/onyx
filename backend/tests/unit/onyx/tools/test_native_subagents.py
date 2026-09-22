import asyncio
from collections.abc import AsyncIterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import NullEmitter
from onyx.llm.pydantic_ai_llm import PydanticAILLM
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallKickoff
from onyx.tools.subagents.coding_agent import run_coding_agent_call
from onyx.tools.subagents.research_agent import run_research_agent_call


def _llm(stream: Any) -> PydanticAILLM:
    llm = MagicMock(spec=PydanticAILLM)
    llm.model = FunctionModel(stream_function=stream)
    llm.config.deployment_name = None
    llm.config.model_name = "test-model"
    llm.config.model_provider = "openai"
    llm.config.max_input_tokens = 100000
    llm.model_settings.return_value = {}
    return llm


@pytest.mark.asyncio
@pytest.mark.parametrize("delegated", [False, True])
async def test_coding_agent_native_history_contains_bash_result_before_final_answer(
    delegated: bool,
) -> None:
    requests: list[list[ModelMessage]] = []

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        requests.append(list(messages))
        if len(requests) == 1:
            yield {
                0: DeltaToolCall(
                    name="bash", json_args='{"cmd":"ls"}', tool_call_id="bash-1"
                )
            }
        elif len(requests) == 2:
            yield {
                0: DeltaToolCall(
                    name="generate_answer", json_args="{}", tool_call_id="finish-1"
                )
            }
        else:
            assert not info.function_tools
            yield "The repository contains README.md."

    @contextmanager
    def session(**kwargs: Any):
        del kwargs
        yield "sandbox-session"

    call = ToolCallKickoff(
        tool_call_id="coding",
        tool_name="coding_agent",
        tool_args={"query": "List files", "github_repo": "owner/repo"},
        placement=Placement(turn_index=0, tab_index=0),
    )
    with (
        patch("onyx.tools.subagents.coding_agent._setup_session", session),
        patch(
            "onyx.tools.subagents.coding_agent._run_bash_call",
            return_value="README.md",
        ) as execute,
    ):
        result = await run_coding_agent_call(
            RunContext(deps=None, model=TestModel(), usage=RunUsage())
            if delegated
            else None,
            call,
            NullEmitter(),
            _llm(stream),
            len,
            None,
        )
    assert result is not None
    assert result.answer == "The repository contains README.md."
    execute.assert_called_once()
    assert any(
        isinstance(part, ToolReturnPart)
        and part.tool_call_id == "bash-1"
        and part.content == "README.md"
        for message in requests[-1]
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


@pytest.mark.asyncio
async def test_research_agent_report_control_changes_native_request_tools() -> None:
    requests: list[list[ModelMessage]] = []

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        requests.append(list(messages))
        if len(requests) == 1:
            yield {
                0: DeltaToolCall(
                    name="generate_report", json_args="{}", tool_call_id="report-1"
                )
            }
        else:
            assert not info.function_tools
            yield "The research is complete."

    call = ToolCallKickoff(
        tool_call_id="research",
        tool_name="research_agent",
        tool_args={"task": "Investigate the topic"},
        placement=Placement(turn_index=0, tab_index=0),
    )
    result = await run_research_agent_call(
        RunContext(deps=None, model=TestModel(), usage=RunUsage()),
        call,
        "parent",
        [],
        NullEmitter(),
        ChatStateContainer(),
        _llm(stream),
        True,
        len,
        None,
        "",
    )
    assert result is not None
    assert result.intermediate_report == "The research is complete."
    assert len(requests) == 2


def test_deep_research_native_plan_and_report_preserve_final_state() -> None:
    from onyx.chat.models import ChatMessageSimple
    from onyx.configs.constants import MessageType
    from onyx.deep_research.deep_research_agent import run_deep_research_agent

    request_count = 0

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        nonlocal request_count
        del messages
        request_count += 1
        if request_count == 1:
            assert not info.function_tools
            yield "Research the topic and summarize the findings."
        elif request_count == 2:
            yield {
                0: DeltaToolCall(
                    name="generate_report", json_args="{}", tool_call_id="final-report"
                )
            }
        else:
            assert not info.function_tools
            yield "Final research findings."

    state = ChatStateContainer()
    run_deep_research_agent(
        emitter=NullEmitter(),
        state_container=state,
        simple_chat_history=[
            ChatMessageSimple(
                message="Research this topic",
                token_count=3,
                message_type=MessageType.USER,
            )
        ],
        tools=[],
        custom_agent_prompt=None,
        llm=_llm(stream),
        token_counter=len,
        user_language=None,
        skip_clarification=True,
    )
    assert request_count == 3
    assert state.get_answer_tokens() == "Final research findings."


def test_research_branches_run_concurrently_and_count_one_model_turn() -> None:
    from threading import Barrier

    from onyx.chat.models import ChatMessageSimple
    from onyx.configs.constants import MessageType
    from onyx.deep_research.deep_research_agent import run_deep_research_agent
    from onyx.deep_research.models import ResearchAgentCallResult
    from onyx.server.query_and_chat.streaming_models import TopLevelBranching

    barrier = Barrier(2, timeout=3)
    request_count = 0
    emitter = MagicMock(spec=NullEmitter)
    emitter.cancelled = False

    async def child(**kwargs: Any) -> ResearchAgentCallResult:
        await asyncio.to_thread(barrier.wait)
        return ResearchAgentCallResult(
            intermediate_report=kwargs["research_agent_call"].tool_call_id,
            citation_mapping={},
        )

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            yield "Research two sources."
        elif request_count == 2:
            yield {
                index: DeltaToolCall(
                    name="research_agent",
                    json_args='{"task":"Investigate"}',
                    tool_call_id=f"branch-{index}",
                )
                for index in range(2)
            }
        elif request_count == 3:
            assert info.function_tools
            returned = [
                part
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            ]
            assert {part.content for part in returned} >= {"branch-0", "branch-1"}
            yield {
                0: DeltaToolCall(
                    name="generate_report", json_args="{}", tool_call_id="finish"
                )
            }
        else:
            yield "Final report."

    state = ChatStateContainer()
    with (
        patch(
            "onyx.deep_research.deep_research_agent.run_research_agent_call",
            side_effect=child,
        ),
        patch(
            "onyx.deep_research.deep_research_agent._get_research_agent_tool_id",
            return_value=42,
        ),
    ):
        run_deep_research_agent(
            emitter=emitter,
            state_container=state,
            simple_chat_history=[
                ChatMessageSimple(
                    message="Research", token_count=1, message_type=MessageType.USER
                )
            ],
            tools=[],
            custom_agent_prompt=None,
            llm=_llm(stream),
            token_counter=len,
            user_language=None,
            skip_clarification=True,
        )
    assert request_count == 4
    calls = state.get_tool_calls()
    assert len(calls) == 2
    assert {call.turn_index for call in calls} == {1}
    assert {call.tab_index for call in calls} == {0, 1}
    assert any(
        isinstance(call.kwargs["obj"], TopLevelBranching)
        and call.kwargs["obj"].num_parallel_branches == 2
        for call in emitter.report.call_args_list
    )
