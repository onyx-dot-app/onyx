"""
Unit tests for fast_chat_turn functionality.

This module contains unit tests for the fast_chat_turn function, which handles
chat turn processing with agent-based interactions. The tests use dependency
injection with simple fake versions of all dependencies except for the emitter
(which is created by the unified_event_stream decorator) and dependencies_to_maybe_remove
(which should be passed in by the test writer).
"""

from collections.abc import AsyncIterator
from typing import Any
from typing import List
from uuid import UUID
from uuid import uuid4

import pytest
from agents import AgentOutputSchemaBase
from agents import Handoff
from agents import Model
from agents import ModelResponse
from agents import ModelSettings
from agents import ModelTracing
from agents import Tool
from agents.items import ResponseOutputMessage
from openai.types.responses import ResponseCustomToolCallInputDeltaEvent
from openai.types.responses.response_stream_event import ResponseCompletedEvent
from openai.types.responses.response_stream_event import ResponseCreatedEvent
from openai.types.responses.response_stream_event import ResponseTextDeltaEvent

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.chat.models import PromptConfig
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from tests.unit.onyx.chat.turn.utils import BaseFakeModel
from tests.unit.onyx.chat.turn.utils import create_fake_message
from tests.unit.onyx.chat.turn.utils import create_fake_response
from tests.unit.onyx.chat.turn.utils import create_fake_usage
from tests.unit.onyx.chat.turn.utils import FakeModel
from tests.unit.onyx.chat.turn.utils import get_model_with_response
from tests.unit.onyx.chat.turn.utils import StreamableFakeModel


# =============================================================================
# Helper Functions and Base Classes for DRY Principles
# =============================================================================


class CancellationMixin:
    """Mixin for models that support cancellation testing."""

    def __init__(
        self,
        set_fence_func: Any = None,
        chat_session_id: Any = None,
        redis_client: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[call-arg]
        self.set_fence_func = set_fence_func
        self.chat_session_id = chat_session_id
        self.redis_client = redis_client

    def _should_trigger_cancellation(self, iteration: int) -> bool:
        """Check if cancellation should be triggered at this iteration."""
        return (
            iteration == 2
            and self.set_fence_func
            and self.chat_session_id
            and self.redis_client
        )

    def _trigger_cancellation(self) -> None:
        """Trigger the cancellation signal."""
        if self.set_fence_func and self.chat_session_id and self.redis_client:
            self.set_fence_func(self.chat_session_id, self.redis_client, True)


# =============================================================================
# Test Helper Functions
# =============================================================================


def run_fast_chat_turn(
    sample_messages: list[AgentSDKMessage],
    chat_turn_dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    prompt_config: PromptConfig | None = None,
) -> list[Packet]:
    """Helper function to run fast_chat_turn and collect all packets."""
    from onyx.chat.turn.fast_chat_turn import fast_chat_turn

    if prompt_config is None:
        prompt_config = PromptConfig(
            default_behavior_system_prompt="You are a helpful assistant.",
            custom_instructions=None,
            reminder="Answer the user's question.",
            datetime_aware=False,
        )

    generator = fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
    )
    return list(generator)


def assert_packets_contain_stop(packets: list[Packet]) -> None:
    """Assert that packets contain an OverallStop packet at the end."""
    assert len(packets) >= 1, f"Expected at least 1 packet, got {len(packets)}"
    assert isinstance(packets[-1].obj, OverallStop), "Last packet should be OverallStop"


def assert_cancellation_packets(
    packets: list[Packet], expect_cancelled_message: bool = False
) -> None:
    """Assert packets after cancellation contain expected structure."""
    min_expected = 3 if expect_cancelled_message else 2
    assert (
        len(packets) >= min_expected
    ), f"Expected at least {min_expected} packets after cancellation, got {len(packets)}"

    # Last packet should be OverallStop
    assert packets[-1].obj.type == "stop", "Last packet should be OverallStop"

    # Second-to-last should be SectionEnd
    assert (
        packets[-2].obj.type == "section_end"
    ), "Second-to-last packet should be SectionEnd"

    # If expecting cancelled message, third-to-last should be MessageStart with "Cancelled"
    if expect_cancelled_message:
        assert (
            packets[-3].obj.type == "message_start"
        ), "Third-to-last packet should be MessageStart"
        from onyx.server.query_and_chat.streaming_models import MessageStart

        assert isinstance(
            packets[-3].obj, MessageStart
        ), "Third-to-last packet should be MessageStart instance"
        assert (
            packets[-3].obj.content == "Cancelled"
        ), "MessageStart should contain 'Cancelled'"


def create_cancellation_model(
    model_class: type,
    chat_turn_dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
) -> Model:
    """Helper to create a cancellation model with proper setup."""
    from onyx.chat.stop_signal_checker import set_fence

    return model_class(
        set_fence_func=set_fence,
        chat_session_id=chat_session_id,
        redis_client=chat_turn_dependencies.redis_client,
    )


class FakeCancellationModel(CancellationMixin, StreamableFakeModel):
    """Fake Model that allows triggering stop signal during streaming."""

    def _create_stream_events(
        self,
        message: ResponseOutputMessage | None = None,
        response_id: str = "fake-response-id",
    ) -> AsyncIterator[object]:
        """Create stream events with cancellation support."""

        async def _gen() -> AsyncIterator[object]:  # type: ignore[misc]
            # Create message if not provided
            msg = message if message is not None else create_fake_message()

            final_response = create_fake_response(response_id, msg)

            # 1) created
            yield ResponseCreatedEvent(
                response=final_response, sequence_number=1, type="response.created"
            )

            # 2) stream some text (delta) - trigger stop signal during streaming
            for i in range(5):
                yield ResponseTextDeltaEvent(
                    content_index=0,
                    delta="fake response",
                    item_id="fake-item-id",
                    logprobs=[],
                    output_index=0,
                    sequence_number=2,
                    type="response.output_text.delta",
                )

                # Trigger stop signal after a few deltas
                if self._should_trigger_cancellation(i):
                    self._trigger_cancellation()

            # 3) completed
            yield ResponseCompletedEvent(
                response=final_response, sequence_number=3, type="response.completed"
            )

        return _gen()


class FakeToolCallModel(CancellationMixin, StreamableFakeModel):
    """Fake Model that forces tool calls for testing tool cancellation."""

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list,
        model_settings: ModelSettings,
        tools: List[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: List[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any = None,
    ) -> ModelResponse:
        """Override to create a response with tool calls."""
        message = create_fake_message(
            text="I need to use a tool", include_tool_calls=True
        )
        usage = create_fake_usage()
        return ModelResponse(
            output=[message], usage=usage, response_id="fake-response-id"
        )

    def _create_stream_events(  # type: ignore[override]
        self,
        message: ResponseOutputMessage | None = None,
        response_id: str = "fake-response-id",
    ) -> AsyncIterator[object]:
        """Create stream events with tool calls and cancellation support."""

        async def _gen() -> AsyncIterator[object]:  # type: ignore[misc]
            # Create message if not provided
            msg = (
                message
                if message is not None
                else create_fake_message(
                    text="I need to use a tool", include_tool_calls=True
                )
            )

            final_response = create_fake_response(response_id, msg)

            # 1) created
            yield ResponseCreatedEvent(
                response=final_response, sequence_number=1, type="response.created"
            )

            # 2) stream tool call deltas - trigger stop signal during streaming
            for i in range(5):
                yield ResponseCustomToolCallInputDeltaEvent(
                    delta="fake response",
                    item_id="fake-item-id",
                    output_index=0,
                    sequence_number=2,
                    type="response.custom_tool_call_input.delta",
                )

                # Trigger stop signal after a few deltas
                if self._should_trigger_cancellation(i):
                    self._trigger_cancellation()

            # 3) completed with the full Response object (including tool calls)
            yield ResponseCompletedEvent(
                response=final_response, sequence_number=2, type="response.completed"
            )

        return _gen()


class FakeFailingModel(BaseFakeModel):
    """Simple fake Model implementation for testing exceptions."""

    def stream_response(  # type: ignore[override]
        self,
        system_instructions: str | None,
        input: str | list,
        model_settings: ModelSettings,
        tools: List[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: List[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any = None,
    ) -> AsyncIterator[object]:
        """Stream implementation that raises an exception."""

        async def _gen() -> AsyncIterator[object]:  # type: ignore[misc]
            fake_response = create_fake_response(response_id="fake-response-id")
            yield ResponseCreatedEvent(
                response=fake_response, sequence_number=1, type="response.created"
            )

            # Stream some deltas before failing
            for i in range(5):
                yield ResponseCustomToolCallInputDeltaEvent(
                    delta="fake response",
                    item_id="fake-item-id",
                    output_index=0,
                    sequence_number=2,
                    type="response.custom_tool_call_input.delta",
                )

            # Raise exception to test error handling
            raise Exception("Fake exception")

        return _gen()


@pytest.fixture
def chat_session_id() -> UUID:
    """Fixture providing chat session ID."""
    return uuid4()


@pytest.fixture
def message_id() -> int:
    """Fixture providing message ID."""
    return 123


@pytest.fixture
def research_type() -> ResearchType:
    """Fixture providing research type."""
    return ResearchType.FAST


@pytest.fixture
def fake_failing_model() -> Model:
    return FakeFailingModel()


@pytest.fixture
def fake_tool_call_model() -> Model:
    return FakeToolCallModel()


@pytest.fixture
def sample_messages() -> list[AgentSDKMessage]:
    return [
        SystemMessage(
            role="system",
            content=[
                InputTextContent(
                    type="input_text",
                    text="You are a highly capable assistant",
                )
            ],
        ),
        UserMessage(
            role="user",
            content=[
                InputTextContent(
                    type="input_text",
                    text="hi",
                )
            ],
        ),
    ]


def test_fast_chat_turn_basic(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    """Test that makes sure basic end to end functionality of our
    fast agent chat turn works.
    """
    packets = run_fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
    )
    assert_packets_contain_stop(packets)


def test_fast_chat_turn_catch_exception(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    fake_failing_model: Model,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    """Test that makes sure exceptions in our agent background thread are propagated properly.
    RuntimeWarning: coroutine 'FakeFailingModel.stream_response.<locals>._gen' was never awaited
    is expected.
    """
    from onyx.chat.turn.fast_chat_turn import fast_chat_turn

    chat_turn_dependencies.llm_model = fake_failing_model

    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions=None,
        reminder="Answer the user's question.",
        datetime_aware=False,
    )

    generator = fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
    )
    with pytest.raises(Exception):
        list(generator)


def test_fast_chat_turn_cancellation(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    """Test that cancellation via set_fence works correctly.

    When set_fence is called during message streaming, we should see:
    1. SectionEnd packet (when cancelling during message streaming, no "Cancelled" message is shown)
    2. OverallStop packet

    The "Cancelled" MessageStart is only shown when cancelling during tool calls or reasoning,
    not during regular message streaming.
    """
    # Replace the model with our cancellation model that triggers stop signal during streaming
    cancellation_model = create_cancellation_model(
        FakeCancellationModel, chat_turn_dependencies, chat_session_id
    )
    chat_turn_dependencies.llm_model = cancellation_model

    packets = run_fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
    )

    # After cancellation during message streaming, we should see SectionEnd, then OverallStop
    # The "Cancelled" MessageStart is only shown when cancelling during tool calls/reasoning
    assert_cancellation_packets(packets, expect_cancelled_message=False)


def test_fast_chat_turn_tool_call_cancellation(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    """Test that cancellation via set_fence works correctly during tool calls.

    When set_fence is called during tool execution, we should see:
    1. MessageStart packet with "Cancelled" content
    2. SectionEnd packet
    3. OverallStop packet
    """
    # Replace the model with our tool call model
    cancellation_model = create_cancellation_model(
        FakeToolCallModel, chat_turn_dependencies, chat_session_id
    )
    chat_turn_dependencies.llm_model = cancellation_model

    packets = run_fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
    )

    # After cancellation during tool call, we should see MessageStart, SectionEnd, then OverallStop
    # The "Cancelled" MessageStart is shown when cancelling during tool calls/reasoning
    assert_cancellation_packets(packets, expect_cancelled_message=True)


def test_fast_chat_turn_second_turn_context_handlers(
    chat_turn_dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    from onyx.chat.turn.fast_chat_turn import fast_chat_turn

    """Test that context handlers work correctly in tandem for the next turn."""
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Always be polite and helpful.",
        reminder="Answer the user's question.",
        datetime_aware=False,
    )

    starter_messages = [
        SystemMessage(
            role="system",
            content=[
                InputTextContent(
                    type="input_text",
                    text="You are a helpful assistant.",
                )
            ],
        ),
        UserMessage(
            role="user",
            content=[
                InputTextContent(
                    type="input_text",
                    text="hi",
                )
            ],
        ),
        AssistantMessageWithContent(
            role="assistant",
            content=[
                InputTextContent(
                    type="input_text",
                    text="I need to use a tool",
                )
            ],
        ),
        UserMessage(
            role="user",
            content=[
                InputTextContent(
                    type="input_text",
                    text="hi again",
                )
            ],
        ),
    ]
    generator = fast_chat_turn(
        starter_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
    )
    packets = list(generator)
    assert_packets_contain_stop(packets)
    assert isinstance(chat_turn_dependencies.llm_model, FakeModel)
    input_history = chat_turn_dependencies.llm_model.input_history
    first_input = input_history[0]
    assert isinstance(first_input, list), "First input should be a list"
    assert (
        len(first_input) == 5
    ), f"First input should have at least 3 messages (system, user, assistant, custom instructions, user), got {len(first_input)}"

    assert first_input[0]["role"] == "system", "First message should be system message"  # type: ignore
    assert (
        first_input[1]["role"] == "user"
    ), "Second message should be user message from previous turn"
    assert first_input[2]["role"] == "assistant", "Third message should be assistant message"  # type: ignore
    assert first_input[3]["role"] == "user", "Fourth message should be custom instructions message"  # type: ignore
    assert first_input[4]["role"] == "user", "Fifth message should be user message"  # type: ignore


def test_fast_chat_turn_context_handlers(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    fake_dummy_tool: Any,
) -> None:
    """Test that context handlers work correctly in tandem.

    This test verifies that messages are properly constructed with context handlers:
    - First LLM call: [system, user message, custom instructions]
    - Second LLM call (after tool call): [system, user message, tool call,
      tool call response, custom instructions, user message with reminder]
    """
    from typing import Any

    from agents import Tool as AgentSDKTool

    from onyx.chat.models import PromptConfig
    from onyx.chat.turn.fast_chat_turn import fast_chat_turn

    # Create a model that tracks input history and returns tool call on first call
    class FakeModelWithInputTracking(FakeToolCallModel):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            # input_history to track all inputs
            self.input_history: list[str | list] = []
            self.stream_call_count = 0

        async def get_response(
            self,
            system_instructions: str | None,
            input: str | list,
            model_settings: Any,
            tools: list[AgentSDKTool],
            output_schema: Any,
            handoffs: Any,
            tracing: Any,
            *,
            previous_response_id: str | None = None,
            conversation_id: str | None = None,
            prompt: Any = None,
        ) -> Any:
            """Override to track input history."""
            # Track input
            self.input_history.append(input)
            self.stream_call_count += 1

            # On first call, return tool call
            # On subsequent calls, return regular text response
            if self.stream_call_count == 1:
                # Create a proper tool call response
                # Tool calls go directly in the output list, not inside a message
                from agents import ModelResponse
                from agents.items import ResponseFunctionToolCall

                from tests.unit.onyx.chat.turn.utils import create_fake_usage

                # Create tool call that goes directly in output
                tool_call = ResponseFunctionToolCall(
                    call_id="tool-call-1",
                    name="dummy_tool",
                    arguments="{}",
                    type="function_call",
                    id="tool-call-1",
                )

                usage = create_fake_usage()
                return ModelResponse(
                    output=[tool_call],  # type: ignore[list-item]
                    usage=usage,
                    response_id="fake-response-id-1",
                )
            else:
                # Return regular text response
                from agents import ModelResponse

                from tests.unit.onyx.chat.turn.utils import create_fake_message
                from tests.unit.onyx.chat.turn.utils import create_fake_usage

                message = create_fake_message(text="This is the final answer")
                usage = create_fake_usage()
                return ModelResponse(
                    output=[message], usage=usage, response_id="fake-response-id-2"
                )

        def stream_response(  # type: ignore[override]
            self,
            system_instructions: str | None,
            input: str | list,
            model_settings: Any,
            tools: list[AgentSDKTool],
            output_schema: Any,
            handoffs: Any,
            tracing: Any,
            *,
            previous_response_id: str | None = None,
            conversation_id: str | None = None,
            prompt: Any = None,
        ) -> Any:
            """Override to track input history and return tool call then text."""
            from collections.abc import AsyncIterator

            from openai.types.responses.response_stream_event import (
                ResponseCompletedEvent,
            )
            from openai.types.responses.response_stream_event import (
                ResponseCreatedEvent,
            )
            from openai.types.responses.response_stream_event import (
                ResponseTextDeltaEvent,
            )

            from tests.unit.onyx.chat.turn.utils import create_fake_message
            from tests.unit.onyx.chat.turn.utils import create_fake_response

            # Track input
            self.input_history.append(input)
            self.stream_call_count += 1

            # On first call, return tool call stream
            # On subsequent calls, return regular text response
            if self.stream_call_count == 1:
                # Return tool call stream events
                async def _gen_tool() -> AsyncIterator[object]:  # type: ignore[misc]
                    from agents.items import ResponseFunctionToolCall
                    from openai.types.responses import Response

                    from tests.unit.onyx.chat.turn.utils import (
                        create_fake_response_usage,
                    )

                    # Create tool call that goes directly in output
                    tool_call = ResponseFunctionToolCall(
                        call_id="tool-call-1",
                        name="dummy_tool",
                        arguments="{}",
                        type="function_call",
                    )

                    # Create Response with tool call in output
                    fake_response = Response(
                        id="fake-response-id-1",
                        created_at=1234567890,
                        object="response",
                        output=[tool_call],  # Tool call goes directly in output
                        usage=create_fake_response_usage(),
                        status="completed",
                        model="fake-model",
                        parallel_tool_calls=False,
                        tool_choice="auto",
                        tools=[],
                    )

                    # 1) created
                    yield ResponseCreatedEvent(
                        response=fake_response,
                        sequence_number=1,
                        type="response.created",
                    )

                    # 2) completed (tool calls are in the response already)
                    yield ResponseCompletedEvent(
                        response=fake_response,
                        sequence_number=2,
                        type="response.completed",
                    )

                return _gen_tool()
            else:
                # Return regular text response stream
                async def _gen() -> AsyncIterator[object]:  # type: ignore[misc]
                    from openai.types.responses.response_stream_event import (
                        ResponseContentPartAddedEvent,
                    )
                    from openai.types.responses.response_stream_event import (
                        ResponseContentPartDoneEvent,
                    )

                    from tests.unit.onyx.chat.turn.utils import ResponseOutputText

                    msg = create_fake_message(text="This is the final answer")
                    fake_response = create_fake_response(
                        response_id="fake-response-id-2", message=msg
                    )

                    # 1) created
                    yield ResponseCreatedEvent(
                        response=fake_response,
                        sequence_number=1,
                        type="response.created",
                    )

                    # 2) content_part.added - triggers MessageStart
                    yield ResponseContentPartAddedEvent(
                        content_index=0,
                        item_id="fake-item-id",
                        output_index=0,
                        part=ResponseOutputText(
                            text="", type="output_text", annotations=[]
                        ),
                        sequence_number=2,
                        type="response.content_part.added",
                    )

                    # 3) stream some text deltas
                    yield ResponseTextDeltaEvent(
                        content_index=0,
                        delta="This is the final answer",
                        item_id="fake-item-id",
                        logprobs=[],
                        output_index=0,
                        sequence_number=3,
                        type="response.output_text.delta",
                    )

                    # 4) content_part.done - triggers SectionEnd
                    yield ResponseContentPartDoneEvent(
                        content_index=0,
                        item_id="fake-item-id",
                        output_index=0,
                        part=ResponseOutputText(
                            text="This is the final answer",
                            type="output_text",
                            annotations=[],
                        ),
                        sequence_number=4,
                        type="response.content_part.done",
                    )

                    # 5) completed
                    yield ResponseCompletedEvent(
                        response=fake_response,
                        sequence_number=5,
                        type="response.completed",
                    )

                return _gen()

        @property
        def call_count(self) -> int:
            """Alias for stream_call_count for backward compatibility."""
            return self.stream_call_count

    # Create the fake model with tool
    fake_model_with_tool = FakeModelWithInputTracking()

    # Set up dependencies with the fake model and tool
    chat_turn_dependencies.llm_model = fake_model_with_tool
    chat_turn_dependencies.tools = [fake_dummy_tool]

    # Create a prompt config with custom instructions
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions="Always be polite and helpful.",
        reminder="Answer the user's question.",
        datetime_aware=False,
    )

    # Run the fast chat turn
    # The model will return a tool call on first response, execute the tool,
    # then return a regular text response on second call
    generator = fast_chat_turn(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
    )
    packets = list(generator)

    # Verify that the model was called at least twice (once for tool call, once for final response)
    # Note: call_count might be higher due to multiple method calls
    assert (
        fake_model_with_tool.call_count >= 2
    ), f"Expected model to be called at least twice, but was called {fake_model_with_tool.call_count} times"

    # Verify that we have input history (at least 2 inputs, one for tool call and one for final answer)
    assert (
        len(fake_model_with_tool.input_history) >= 2
    ), f"Expected at least 2 inputs in history, got {len(fake_model_with_tool.input_history)}"

    # Verify first input: [system, user message, custom instructions]
    first_input = fake_model_with_tool.input_history[0]
    assert isinstance(first_input, list), "First input should be a list"
    assert (
        len(first_input) == 3
    ), f"First input should have at least 3 messages (system, user, custom instructions), got {len(first_input)}"

    assert first_input[0]["role"] == "system", "First message should be system message"  # type: ignore
    assert (
        first_input[1]["role"] == "user"  # type: ignore
    ), "Second message should be custom instructions"
    assert first_input[2]["role"] == "user", "Third message should be user message"  # type: ignore

    # Verify second input: [system, user message, tool call, tool call response, custom instructions, user message with reminder]
    second_input = fake_model_with_tool.input_history[1]
    assert isinstance(second_input, list), "Second input should be a list of messages"
    assert len(second_input) == 6, (
        f"Second input should have 6 messages "
        f"(system, user, tool call, tool response, custom instructions, reminder), "
        f"got {len(second_input)}"
    )

    # Check that first message is still system message
    assert (
        second_input[0]["role"] == "system"
    ), "First message in second input should be system message"
    assert (
        second_input[1]["role"] == "user"
    ), "Second message in second input should be custom instructions"
    assert (
        second_input[2]["role"] == "user"
    ), "Third message in second input should be user query"
    assert (
        second_input[3]["type"] == "function_call"
    ), "Fourth message in second input should be tool call invocation"
    assert (
        second_input[4]["type"] == "function_call_output"
    ), "Fifth message in second input should be tool call response"
    assert (
        second_input[5]["role"] == "user"
    ), "Sixth message in second input should be reminder message"
    # Verify that packets were generated successfully
    assert_packets_contain_stop(packets)


def test_fast_chat_turn_citation_processing(
    chat_turn_context: ChatTurnContext,
    sample_messages: list[AgentSDKMessage],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    from onyx.chat.turn.fast_chat_turn import _fast_chat_turn_core
    from onyx.chat.turn.infra.chat_turn_event_stream import unified_event_stream
    from onyx.chat.turn.models import ChatTurnContext as ChatTurnContextType
    from onyx.server.query_and_chat.streaming_models import CitationInfo
    from onyx.server.query_and_chat.streaming_models import MessageStart
    from tests.unit.onyx.chat.turn.utils import create_test_inference_section
    from tests.unit.onyx.chat.turn.utils import create_test_iteration_answer

    # Create test data using helper functions
    fake_inference_section = create_test_inference_section()
    fake_iteration_answer = create_test_iteration_answer()

    # Create a custom model with citation text
    citation_text = "Based on the search results, here's the answer with citations [1]"
    citation_model = get_model_with_response(
        response_text=citation_text, stream_word_by_word=True
    )
    chat_turn_context.run_dependencies.llm_model = citation_model

    # Create a fake prompt config
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        custom_instructions=None,
        reminder="Answer the user's question.",
        datetime_aware=False,
    )

    # Set up the chat turn context with citation-related data
    chat_turn_context.global_iteration_responses = [fake_iteration_answer]
    chat_turn_context.tool_calls_processed_by_citation_context_handler = 1

    # Populate fetched_documents_cache with the document we're citing
    from onyx.chat.turn.models import FetchedDocumentCacheEntry

    chat_turn_context.fetched_documents_cache = {
        "test-doc-1": FetchedDocumentCacheEntry(
            inference_section=fake_inference_section,
            document_citation_number=1,
        )
    }

    chat_turn_context.citations = [
        CitationInfo(
            citation_num=1,
            document_id="test-doc-1",
        )
    ]

    # Create a decorated version of _fast_chat_turn_core for testing
    @unified_event_stream
    def test_fast_chat_turn_core(
        messages: list[AgentSDKMessage],
        dependencies: ChatTurnDependencies,
        session_id: UUID,
        msg_id: int,
        res_type: ResearchType,
        p_config: PromptConfig,
        context: ChatTurnContextType,
    ) -> None:
        _fast_chat_turn_core(
            messages,
            dependencies,
            session_id,
            msg_id,
            res_type,
            p_config,
            starter_context=context,
        )

    # Run the test with the core function
    generator = test_fast_chat_turn_core(
        sample_messages,
        chat_turn_context.run_dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
        chat_turn_context,
    )
    packets = list(generator)

    # Verify we get the expected packets including citation events
    assert_packets_contain_stop(packets)

    # Collect all packet data
    message_start_found = False
    citation_start_found = False
    citation_delta_found = False
    citation_section_end_found = False
    message_start_index = None
    citation_start_index = None
    collected_text = ""

    for packet in packets:
        if isinstance(packet.obj, MessageStart):
            message_start_found = True
            message_start_index = packet.ind
            # Verify that final_documents is populated with cited documents
            if (
                packet.obj.final_documents is not None
                and len(packet.obj.final_documents) > 0
            ):
                # Verify the document ID matches our test document
                assert packet.obj.final_documents[0].document_id == "test-doc-1"
        elif packet.obj.type == "message_delta":
            # Collect text from message deltas
            if hasattr(packet.obj, "content") and packet.obj.content:
                collected_text += packet.obj.content
        elif isinstance(packet.obj, CitationStart):
            citation_start_found = True
            citation_start_index = packet.ind
        elif isinstance(packet.obj, CitationDelta):
            citation_delta_found = True
            # Verify citation info is present
            assert packet.obj.citations is not None
            assert len(packet.obj.citations) > 0
            # Verify citation points to our test document
            citation = packet.obj.citations[0]
            assert citation.document_id == "test-doc-1"
            assert citation.citation_num == 1
            # Verify citation packet has the same index as citation start
            assert packet.ind == citation_start_index
        elif (
            isinstance(packet.obj, SectionEnd)
            and citation_start_found
            and citation_delta_found
        ):
            citation_section_end_found = True
            # Verify citation section end has the same index
            assert packet.ind == citation_start_index

    # Verify all expected events were emitted
    assert message_start_found, "MessageStart event should be emitted"
    assert citation_start_found, "CitationStart event should be emitted"
    assert citation_delta_found, "CitationDelta event should be emitted"
    assert citation_section_end_found, "Citation section should end with SectionEnd"

    # Verify that citation packets are emitted after message packets (higher index)
    assert message_start_index is not None, "message_start_index should be set"
    assert citation_start_index is not None, "citation_start_index should be set"
    assert (
        citation_start_index > message_start_index
    ), f"Citation packets (index {citation_start_index}) > message start (index {message_start_index})"

    # Verify the collected text contains the expected citation format
    assert (
        "[[1]](https://example.com/test-doc)" in collected_text
    ), f"Expected citation link not found in collected text: {collected_text}"
