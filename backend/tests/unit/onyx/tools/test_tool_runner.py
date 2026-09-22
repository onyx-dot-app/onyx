"""Native dispatch preserves domain results and cancellation without batch merging."""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext

from onyx.server.query_and_chat.placement import Placement
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallKickoff, ToolResponse
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)
from onyx.tools.tool_runner import run_tool_call_async


@pytest.mark.parametrize("coding", [False, True])
def test_native_dispatch_returns_exact_call_identity(coding: bool) -> None:
    async def run() -> None:
        loop_thread = threading.get_ident()
        tool = MagicMock(spec=CodingAgentTool if coding else Tool)
        tool.name = "coding_agent" if coding else "custom_action"
        expected = ToolResponse(rich_response=None, llm_facing_response="completed")

        def execute(**_kwargs: object) -> ToolResponse:
            assert threading.get_ident() != loop_thread
            return expected

        tool.run.side_effect = execute
        if coding:
            tool.run_async = AsyncMock(return_value=expected)
        call = ToolCallKickoff(
            tool_call_id="original-call",
            tool_name=tool.name,
            tool_args={"query": "inspect"},
            placement=Placement(turn_index=3, tab_index=2),
        )
        context = MagicMock(spec=RunContext)
        result = await run_tool_call_async(
            context=context,
            tool_call=call,
            tools=[tool],
            message_history=[],
            user_memory_context=None,
            user_info=None,
            citation_mapping={},
            next_citation_num=10,
        )
        assert result is expected
        assert result.tool_call is call
        if coding:
            tool.run_async.assert_awaited_once()
            assert tool.run_async.call_args.args == (context,)
            tool.run.assert_not_called()
        else:
            tool.run.assert_called_once()
        tool.emitter.report.assert_called_once()

    asyncio.run(run())


def test_native_coding_cancellation_propagates_without_success_event() -> None:
    async def run() -> None:
        tool = MagicMock(spec=CodingAgentTool)
        tool.name = "coding_agent"
        started = asyncio.Event()

        async def execute(*_args: object, **_kwargs: object) -> ToolResponse:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("Cancelled coding task resumed")

        tool.run_async = AsyncMock(side_effect=execute)
        task = asyncio.create_task(
            run_tool_call_async(
                context=MagicMock(spec=RunContext),
                tool_call=ToolCallKickoff(
                    tool_call_id="cancel",
                    tool_name=tool.name,
                    tool_args={},
                    placement=Placement(turn_index=0),
                ),
                tools=[tool],
                message_history=[],
                user_memory_context=None,
                user_info=None,
                citation_mapping={},
                next_citation_num=1,
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        tool.emitter.report.assert_not_called()

    asyncio.run(run())
