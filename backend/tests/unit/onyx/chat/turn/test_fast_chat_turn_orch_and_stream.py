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
            system_prompt="You are a helpful assistant.",
            task_prompt="Answer the user's question.",
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
        system_prompt="You are a helpful assistant.",
        task_prompt="Answer the user's question.",
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
    from tests.unit.onyx.chat.turn.utils import create_test_llm_doc

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
        system_prompt="You are a helpful assistant.",
        task_prompt="Answer the user's question.",
        datetime_aware=False,
    )

    # Set up the chat turn context with citation-related data
    chat_turn_context.global_iteration_responses = [fake_iteration_answer]
    chat_turn_context.tool_calls_processed_by_citation_context_handler = 1
    chat_turn_context.unordered_fetched_inference_sections = [fake_inference_section]
    chat_turn_context.ordered_fetched_documents = [
        create_test_llm_doc(document_citation_number=1)
    ]
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
