from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from queue import Queue
from unittest.mock import Mock

import pytest
from pydantic_ai import messages as pm
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition

from onyx.chat.agent_runtime import NativeAgentRequest, run_native_agent
from onyx.chat.emitter import Emitter
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import PydanticAIEvent


def definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_native_agent_preserves_tool_results_and_stream_events() -> None:
    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = TestModel(call_tools=["search"], custom_output_text="done")
    queue = Queue()
    histories = []
    responses = []
    batches = 0

    def prepare(messages: list[pm.ModelMessage]) -> NativeAgentRequest:
        histories.append(list(messages))
        return NativeAgentRequest(messages, {}, [ToolDefinition(name="search")])

    def execute(_call: pm.ToolCallPart) -> str:
        nonlocal batches
        batches += 1
        return "tenant-result"

    output = run_native_agent(
        llm=llm,
        prepare_step=prepare,
        finalize_step=responses.append,
        execute_tool=execute,
        tool_definitions=[definition()],
        max_requests=2,
        emitter=Emitter(queue),
        state_container=None,
        placement=lambda: Placement(turn_index=0),
        message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
    )
    assert output == "done"
    assert batches == 1
    assert any(
        isinstance(part, pm.ToolReturnPart) and part.content == "tenant-result"
        for message in histories[1]
        for part in message.parts
    )
    packets = [queue.get_nowait()[1] for _ in range(queue.qsize())]
    events = [
        packet.obj.event
        for packet in packets
        if isinstance(packet.obj, PydanticAIEvent)
    ]
    assert any(event["event_kind"] == "part_start" for event in events)
    assert any(event["event_kind"] == "function_tool_call" for event in events)
    assert any(event["event_kind"] == "function_tool_result" for event in events)


def test_native_agent_enforces_request_limit() -> None:
    async def stream(_messages, _info):
        yield {0: DeltaToolCall(name="search", json_args="{}", tool_call_id="repeat")}

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    with pytest.raises(UsageLimitExceeded):
        run_native_agent(
            llm=llm,
            prepare_step=lambda messages: NativeAgentRequest(
                messages, {}, [ToolDefinition(name="search")]
            ),
            finalize_step=lambda _response: None,
            execute_tool=lambda _call: "again",
            tool_definitions=[definition()],
            max_requests=2,
            emitter=Emitter(Queue()),
            state_container=None,
            placement=lambda: Placement(turn_index=0),
            message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
        )


def test_parallel_native_agents_keep_tenant_context() -> None:
    tenant_context: ContextVar[str] = ContextVar("agent_test_tenant")

    def run(tenant: str) -> str:
        token = tenant_context.set(tenant)
        llm = Mock(spec=LLM)
        llm.config = LLMConfig(
            model_provider="openai",
            model_name="gpt-5-mini",
            max_input_tokens=8000,
            temperature=0,
        )
        llm.model = TestModel(call_tools=[], custom_output_text=tenant)

        def prepare(messages: list[pm.ModelMessage]) -> NativeAgentRequest:
            assert tenant_context.get() == tenant
            return NativeAgentRequest(messages, {}, [])

        def finalize(_response: pm.ModelResponse) -> None:
            assert tenant_context.get() == tenant

        try:
            return run_native_agent(
                llm=llm,
                prepare_step=prepare,
                finalize_step=finalize,
                execute_tool=lambda _call: "",
                tool_definitions=[],
                max_requests=1,
                emitter=Emitter(Queue()),
                state_container=None,
                placement=lambda: Placement(turn_index=0),
                message_history=[pm.ModelRequest(parts=[pm.UserPromptPart(tenant)])],
            )
        finally:
            tenant_context.reset(token)

    tenants = [f"tenant-{index}" for index in range(20)]
    with ThreadPoolExecutor(max_workers=5) as executor:
        assert list(executor.map(run, tenants)) == tenants


def test_invalid_tool_arguments_never_reach_domain_execution() -> None:
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    async def stream(_messages, _info):
        yield {
            0: DeltaToolCall(
                name="search", json_args='{"query":42}', tool_call_id="invalid"
            )
        }

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    execute = Mock(return_value="must not run")
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    tool = definition()
    tool["function"]["parameters"] = schema
    with pytest.raises(UnexpectedModelBehavior):
        run_native_agent(
            llm=llm,
            prepare_step=lambda messages: NativeAgentRequest(
                messages,
                {},
                [ToolDefinition(name="search", parameters_json_schema=schema)],
            ),
            finalize_step=lambda _response: None,
            execute_tool=execute,
            tool_definitions=[tool],
            max_requests=4,
            emitter=Emitter(Queue()),
            state_container=None,
            placement=lambda: Placement(turn_index=0),
            message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
        )
    execute.assert_not_called()


def test_citations_transform_display_events_without_changing_native_history() -> None:
    from onyx.chat.chat_state import ChatStateContainer
    from onyx.chat.citation_processor import DynamicCitationProcessor
    from onyx.configs.constants import DocumentSource
    from onyx.context.search.models import SearchDoc
    from onyx.server.query_and_chat.streaming_models import CitationInfo

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = TestModel(call_tools=[], custom_output_text="Answer [1].")
    queue = Queue()
    state = ChatStateContainer()
    processor = DynamicCitationProcessor()
    processor.update_citation_mapping(
        {
            1: SearchDoc(
                document_id="doc",
                chunk_ind=0,
                semantic_identifier="Document",
                link="https://example.com/doc",
                blurb="Source",
                source_type=DocumentSource.WEB,
                boost=1,
                hidden=False,
                metadata={},
                score=1,
                match_highlights=[],
            )
        }
    )
    responses = []
    run_native_agent(
        llm=llm,
        prepare_step=lambda messages: NativeAgentRequest(messages, {}, []),
        finalize_step=responses.append,
        execute_tool=lambda _call: "",
        tool_definitions=[],
        max_requests=1,
        emitter=Emitter(queue),
        state_container=state,
        placement=lambda: Placement(turn_index=0),
        message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
        citation_processor=processor,
    )
    packets = [queue.get_nowait()[1] for _ in range(queue.qsize())]
    text = "".join(
        packet.obj.text_delta
        for packet in packets
        if isinstance(packet.obj, PydanticAIEvent)
    )
    assert text == "Answer [[1]](https://example.com/doc)."
    assert state.answer_tokens == text
    assert any(isinstance(packet.obj, CitationInfo) for packet in packets)
    assert responses[-1].parts[0].content == "Answer [1]."
    llm.record_usage.assert_called_once()


def test_disconnect_cancels_a_paused_native_stream() -> None:
    import asyncio
    import threading
    import time

    from pydantic_ai.exceptions import RunCancelled

    cancelled = threading.Event()
    closed = threading.Event()

    async def stream(_messages, _info):
        try:
            yield "partial"
            cancelled.set()
            await asyncio.sleep(60)
            yield "unreachable"
        finally:
            closed.set()

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    started = time.monotonic()
    with pytest.raises(RunCancelled):
        run_native_agent(
            llm=llm,
            prepare_step=lambda messages: NativeAgentRequest(messages, {}, []),
            finalize_step=lambda _response: None,
            execute_tool=lambda _call: "",
            tool_definitions=[],
            max_requests=1,
            emitter=Emitter(Queue(), drain_done=cancelled),
            state_container=None,
            placement=lambda: Placement(turn_index=0),
            message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
        )
    assert time.monotonic() - started < 3
    assert closed.is_set()
    llm.record_usage.assert_called_once()


def test_native_compaction_preserves_tool_pairs_and_latest_question() -> None:
    from pydantic_ai_harness.compaction import estimate_token_count

    received: list[pm.ModelMessage] = []

    async def stream(messages, _info):
        received.extend(messages)
        yield "done"

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="custom",
        max_input_tokens=800,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    history: list[pm.ModelMessage] = [
        pm.ModelRequest(parts=[pm.SystemPromptPart("Required system instructions")]),
        pm.ModelRequest(
            parts=[pm.UserPromptPart("Required project context")],
            metadata={"onyx_prompt": True},
        ),
        pm.ModelRequest(parts=[pm.UserPromptPart("Original question")]),
    ]
    for index in range(12):
        history.extend(
            [
                pm.ModelResponse(
                    parts=[
                        pm.ToolCallPart(
                            "search", {"query": str(index)}, tool_call_id=str(index)
                        )
                    ]
                ),
                pm.ModelRequest(
                    parts=[
                        pm.ToolReturnPart(
                            "search", "result " * 400, tool_call_id=str(index)
                        )
                    ]
                ),
            ]
        )
    history.append(pm.ModelRequest(parts=[pm.UserPromptPart("Latest question")]))
    history.append(
        pm.ModelRequest(
            parts=[pm.UserPromptPart("Required reminder")],
            metadata={"onyx_prompt": True, "onyx_reminder": True},
        )
    )
    run_native_agent(
        llm=llm,
        prepare_step=lambda messages: NativeAgentRequest(messages, {}, []),
        finalize_step=lambda _response: None,
        execute_tool=lambda _call: "",
        tool_definitions=[],
        max_requests=1,
        emitter=Emitter(Queue()),
        state_container=None,
        placement=lambda: Placement(turn_index=0),
        message_history=history,
        tokenizer=lambda text: len(text.split()),
    )
    assert estimate_token_count(received, lambda text: len(text.split())) < 800
    assert any(
        isinstance(part, pm.UserPromptPart) and part.content == "Latest question"
        for message in received
        for part in message.parts
    )
    calls = {
        part.tool_call_id
        for message in received
        for part in message.parts
        if isinstance(part, pm.ToolCallPart)
    }
    returns = {
        part.tool_call_id
        for message in received
        for part in message.parts
        if isinstance(part, pm.ToolReturnPart)
    }
    assert calls == returns
    assert isinstance(received[0].parts[0], pm.SystemPromptPart)
    assert received[0].parts[0].content == "Required system instructions"
    contents = [
        part.content
        for message in received
        for part in message.parts
        if isinstance(part, pm.UserPromptPart)
    ]
    assert "Required project context" in contents
    assert "Required reminder" in contents


def test_native_tools_execute_in_parallel() -> None:
    import threading

    barrier = threading.Barrier(2, timeout=2)
    requests = 0

    async def stream(_messages, _info):
        nonlocal requests
        requests += 1
        if requests == 1:
            yield {
                0: DeltaToolCall(name="search", json_args="{}", tool_call_id="one"),
                1: DeltaToolCall(name="search", json_args="{}", tool_call_id="two"),
            }
        else:
            yield "done"

    def execute(call: pm.ToolCallPart) -> str:
        barrier.wait()
        return call.tool_call_id

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    assert (
        run_native_agent(
            llm=llm,
            prepare_step=lambda messages: NativeAgentRequest(
                messages, {}, [ToolDefinition(name="search")]
            ),
            finalize_step=lambda _response: None,
            execute_tool=execute,
            tool_definitions=[definition()],
            max_requests=2,
            emitter=Emitter(Queue()),
            state_container=None,
            placement=lambda: Placement(turn_index=0),
            message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
        )
        == "done"
    )


def test_signed_thinking_survives_native_tool_history() -> None:
    from pydantic_ai.models.function import DeltaThinkingPart

    requests = 0
    signed_parts: list[pm.ThinkingPart] = []

    async def stream(messages, _info):
        nonlocal requests
        requests += 1
        if requests == 1:
            yield {
                0: DeltaThinkingPart(
                    content="thinking", signature="signed-provider-data"
                )
            }
            yield {1: DeltaToolCall(name="search", json_args="{}", tool_call_id="call")}
        else:
            signed_parts.extend(
                part
                for message in messages
                for part in message.parts
                if isinstance(part, pm.ThinkingPart)
            )
            yield "done"

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="anthropic",
        model_name="claude-haiku-4-5",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    run_native_agent(
        llm=llm,
        prepare_step=lambda messages: NativeAgentRequest(
            messages, {}, [ToolDefinition(name="search")]
        ),
        finalize_step=lambda _response: None,
        execute_tool=lambda _call: "found",
        tool_definitions=[definition()],
        max_requests=2,
        emitter=Emitter(Queue()),
        state_container=None,
        placement=lambda: Placement(turn_index=0),
        message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
    )
    assert len(signed_parts) == 1
    assert signed_parts[0].signature == "signed-provider-data"


def test_nested_phase_keeps_parent_placement_without_answer_metadata() -> None:
    from pydantic_ai.models.function import DeltaThinkingPart

    from onyx.server.query_and_chat.streaming_models import AnswerMetadata

    async def stream(_messages, _info):
        yield {0: DeltaThinkingPart(content="thinking")}
        yield "child report"

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    queue = Queue()
    run_native_agent(
        llm=llm,
        prepare_step=lambda messages: NativeAgentRequest(messages, {}, []),
        finalize_step=lambda _response: None,
        execute_tool=lambda _call: "",
        tool_definitions=[],
        max_requests=1,
        emitter=Emitter(queue),
        state_container=None,
        placement=lambda: Placement(turn_index=7, tab_index=2, sub_turn_index=3),
        message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
        event_phase=lambda: "report",
    )
    packets = [queue.get_nowait()[1] for _ in range(queue.qsize())]
    assert all(
        packet.placement.turn_index == 7 and packet.placement.tab_index == 2
        for packet in packets
    )
    assert not any(isinstance(packet.obj, AnswerMetadata) for packet in packets)
    text = next(
        packet
        for packet in packets
        if isinstance(packet.obj, PydanticAIEvent) and packet.obj.text_delta
    )
    assert text.placement.sub_turn_index == 4
    assert text.obj.phase == "report"


def test_native_total_timeout_closes_silent_provider() -> None:
    import asyncio
    import threading

    closed = threading.Event()

    async def stream(_messages, _info):
        try:
            yield "partial"
            await asyncio.sleep(60)
        finally:
            closed.set()

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    with pytest.raises(TimeoutError):
        run_native_agent(
            llm=llm,
            prepare_step=lambda messages: NativeAgentRequest(messages, {}, []),
            finalize_step=lambda _response: None,
            execute_tool=lambda _call: "",
            tool_definitions=[],
            max_requests=1,
            emitter=Emitter(Queue()),
            state_container=None,
            placement=lambda: Placement(turn_index=0),
            message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
            total_timeout=0.1,
        )
    assert closed.is_set()


def test_selected_tools_use_native_sequential_barriers() -> None:
    import threading
    import time

    requests = 0
    active = 0
    maximum_active = 0
    lock = threading.Lock()
    calls: list[str] = []

    async def stream(_messages, _info):
        nonlocal requests
        requests += 1
        if requests == 1:
            yield {
                0: DeltaToolCall(name="search", json_args="{}", tool_call_id="one"),
                1: DeltaToolCall(name="search", json_args="{}", tool_call_id="two"),
            }
        else:
            yield "done"

    def execute(call: pm.ToolCallPart) -> str:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
            calls.append(call.tool_call_id)
        return call.tool_call_id

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    run_native_agent(
        llm=llm,
        prepare_step=lambda messages: NativeAgentRequest(
            messages, {}, [ToolDefinition(name="search")]
        ),
        finalize_step=lambda _response: None,
        execute_tool=execute,
        tool_definitions=[definition()],
        max_requests=2,
        emitter=Emitter(Queue()),
        state_container=None,
        placement=lambda: Placement(turn_index=0),
        message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
        sequential_tool_names=frozenset({"search"}),
    )
    assert maximum_active == 1
    assert calls == ["one", "two"]


def test_cancelled_tool_rejects_late_worker_state_updates() -> None:
    import threading
    import time

    from onyx.tools.progress import check_tool_run_active

    completed = threading.Event()
    mutations: list[str] = []

    def execute(_call: pm.ToolCallPart) -> str:
        try:
            time.sleep(0.2)
            check_tool_run_active()
            mutations.append("late result")
            return "done"
        finally:
            completed.set()

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = TestModel(call_tools=["search"], custom_output_text="done")
    with pytest.raises(TimeoutError):
        run_native_agent(
            llm=llm,
            prepare_step=lambda messages: NativeAgentRequest(
                messages, {}, [ToolDefinition(name="search")]
            ),
            finalize_step=lambda _response: None,
            execute_tool=execute,
            tool_definitions=[definition()],
            max_requests=2,
            emitter=Emitter(Queue()),
            state_container=None,
            placement=lambda: Placement(turn_index=0),
            message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
            total_timeout=0.1,
        )
    assert completed.is_set()
    assert mutations == []


@pytest.mark.asyncio
async def test_parent_scope_cancels_nested_silent_native_agent() -> None:
    import asyncio
    import threading

    from pydantic_ai import RunContext
    from pydantic_ai.exceptions import RunCancelled

    from onyx.tools.progress import route_tool_progress

    started = threading.Event()
    closed = threading.Event()

    async def stream(_messages, _info):
        try:
            yield "partial"
            started.set()
            await asyncio.sleep(60)
        finally:
            closed.set()

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)
    emitter = Emitter(Queue())
    with route_tool_progress(Mock(spec=RunContext)):
        child = asyncio.create_task(
            asyncio.to_thread(
                run_native_agent,
                llm=llm,
                prepare_step=lambda messages: NativeAgentRequest(messages, {}, []),
                finalize_step=lambda _response: None,
                execute_tool=lambda _call: "",
                tool_definitions=[],
                max_requests=1,
                emitter=emitter,
                state_container=None,
                placement=lambda: Placement(turn_index=0),
                message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
            )
        )
        assert await asyncio.to_thread(started.wait, 3)
    with pytest.raises(RunCancelled):
        await asyncio.wait_for(child, timeout=3)
    assert closed.is_set()
    assert not emitter.cancelled


@pytest.mark.asyncio
@pytest.mark.parametrize("anchored", [False, True])
@pytest.mark.parametrize("instructions", ["", "instructions " * 100])
async def test_compaction_counts_tool_schema_once(
    anchored: bool, instructions: str
) -> None:
    from pydantic_ai import RunContext
    from pydantic_ai.messages import InstructionPart
    from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
    from pydantic_ai.usage import RequestUsage

    from onyx.chat.agent_runtime import RequestCompaction

    history: list[pm.ModelMessage] = [
        pm.ModelRequest(parts=[pm.SystemPromptPart("system " * 100)]),
        pm.ModelRequest(
            parts=[pm.UserPromptPart("history " * 300)], instructions=instructions
        ),
        pm.ModelResponse(
            parts=[pm.TextPart("answer " * 280)],
            usage=RequestUsage(input_tokens=890 if anchored else 0, output_tokens=10),
        ),
        pm.ModelRequest(parts=[pm.UserPromptPart("latest")], instructions=instructions),
    ]
    request = ModelRequestContext(
        model=TestModel(),
        messages=history,
        model_settings=None,
        model_request_parameters=ModelRequestParameters(
            instruction_parts=[InstructionPart(content=instructions)],
            function_tools=[ToolDefinition(name="search", description="schema " * 200)],
        ),
    )
    result = await RequestCompaction(
        1000, lambda text: len(text.split())
    ).before_model_request(
        Mock(spec=RunContext, model=request.model),
        request,
    )
    assert [message.parts for message in result.messages] == [
        message.parts for message in history
    ]


def test_request_budget_counts_authoritative_instructions_once() -> None:
    from pydantic_ai.messages import InstructionPart
    from pydantic_ai.models import ModelRequestParameters

    from onyx.chat.agent_runtime import estimate_request_tokens

    messages: list[pm.ModelMessage] = [
        pm.ModelRequest(
            parts=[pm.UserPromptPart("question")],
            instructions="old " * 500,
        )
    ]
    parameters = ModelRequestParameters(
        instruction_parts=[InstructionPart(content="new " * 100)]
    )
    assert (
        estimate_request_tokens(messages, parameters, lambda text: len(text.split()))
        == 102
    )


def test_native_subagent_cancellation_stays_on_parent_event_loop() -> None:
    import asyncio
    import threading

    from pydantic_ai import RunContext

    from onyx.chat.agent_runtime import build_native_agent

    loops: list[asyncio.AbstractEventLoop] = []
    child_closed = threading.Event()

    async def child_stream(_messages, _info):
        loops.append(asyncio.get_running_loop())
        try:
            yield "child started"
            await asyncio.sleep(60)
        finally:
            child_closed.set()

    parent = Mock(spec=LLM)
    parent.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    parent.model = TestModel(call_tools=["search"], custom_output_text="done")
    child_llm = Mock(spec=LLM)
    child_llm.config = parent.config
    child_llm.model = FunctionModel(stream_function=child_stream)
    emitter = Emitter(Queue())

    async def delegate(context: RunContext[None], _call: pm.ToolCallPart) -> str:
        loops.append(asyncio.get_running_loop())
        child = build_native_agent(
            llm=child_llm,
            prepare_step=lambda messages: NativeAgentRequest(messages, {}, []),
            finalize_step=lambda _response: None,
            tool_definitions=[],
            max_requests=1,
            emitter=emitter,
            state_container=None,
            placement=lambda: Placement(turn_index=0, sub_turn_index=0),
            message_history=[],
        )
        return await child.delegate(context, "Research")

    with pytest.raises(TimeoutError):
        run_native_agent(
            llm=parent,
            prepare_step=lambda messages: NativeAgentRequest(
                messages, {}, [ToolDefinition(name="search")]
            ),
            finalize_step=lambda _response: None,
            execute_tool_async=delegate,
            tool_definitions=[definition()],
            max_requests=2,
            emitter=emitter,
            state_container=None,
            placement=lambda: Placement(turn_index=0),
            message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
            total_timeout=0.2,
        )
    assert len(loops) == 2 and loops[0] is loops[1]
    assert child_closed.is_set()
    child_llm.record_usage.assert_called_once()
