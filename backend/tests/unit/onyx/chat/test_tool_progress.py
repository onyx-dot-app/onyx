import asyncio
from queue import Queue
from unittest.mock import Mock

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel

from onyx.chat.emitter import Emitter, NullEmitter
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet, SearchToolStart
from onyx.tools.progress import (
    OnyxToolProgress,
    check_tool_run_active,
    publish_tool_progress,
    route_tool_progress,
)


@pytest.mark.asyncio
async def test_tool_progress_uses_native_stream_once() -> None:
    queue: Queue[tuple[int, Packet | Exception | object]] = Queue()
    emitter = Emitter(queue)
    agent = Agent[None, str](TestModel())

    @agent.tool
    async def search(context: RunContext[None]) -> str:
        def report() -> str:
            emitter.report(placement=Placement(turn_index=2), obj=SearchToolStart())
            return "found"

        with route_tool_progress(context):
            return await asyncio.to_thread(report)

    async with agent.run_stream_events("Search") as stream:
        events = [event async for event in stream]
    progress = [event for event in events if isinstance(event, OnyxToolProgress)]
    assert len(progress) == 1
    assert progress[0].tool_name == "search"
    assert progress[0].placement.turn_index == 2
    assert queue.empty()


def test_progress_outside_agent_keeps_model_placement() -> None:
    queue: Queue[tuple[int, Packet | Exception | object]] = Queue()
    emitter = Emitter(queue, model_idx=3)
    emitter.report(placement=Placement(turn_index=4), obj=SearchToolStart())
    model_index, packet = queue.get_nowait()
    assert model_index == 3
    assert isinstance(packet, Packet)
    assert packet.placement.model_index == 3
    assert packet.placement.turn_index == 4


def test_null_reporter_discards_domain_progress() -> None:
    NullEmitter().report(placement=Placement(turn_index=0), obj=SearchToolStart())


@pytest.mark.asyncio
async def test_nested_tool_rejects_results_when_parent_scope_closes() -> None:
    context = Mock(spec=RunContext)
    inner_started = asyncio.Event()
    parent_closed = asyncio.Event()

    async def nested_tool() -> None:
        with route_tool_progress(context):
            check_tool_run_active()
            inner_started.set()
            await parent_closed.wait()
            with pytest.raises(asyncio.CancelledError):
                check_tool_run_active()
            with pytest.raises(asyncio.CancelledError):
                publish_tool_progress(Placement(turn_index=0), SearchToolStart())

    with route_tool_progress(context):
        nested = asyncio.create_task(nested_tool())
        await inner_started.wait()
    parent_closed.set()
    await nested
    context.emit.assert_not_called()
    check_tool_run_active()
