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
from unittest.mock import Mock
from uuid import UUID
from uuid import uuid4

import pytest
from agents import AgentOutputSchemaBase
from agents import FunctionTool
from agents import Handoff
from agents import Model
from agents import ModelResponse
from agents import ModelSettings
from agents import ModelTracing
from agents import Tool
from agents import Usage
from agents.items import ResponseOutputMessage
from agents.items import ResponseOutputText
from openai.types.responses import Response
from openai.types.responses import ResponseCustomToolCallInputDeltaEvent
from openai.types.responses.response_stream_event import ResponseCompletedEvent
from openai.types.responses.response_stream_event import ResponseCreatedEvent
from openai.types.responses.response_stream_event import ResponseTextDeltaEvent
from openai.types.responses.response_usage import InputTokensDetails
from openai.types.responses.response_usage import OutputTokensDetails
from openai.types.responses.response_usage import ResponseUsage

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.chat.models import PromptConfig
from onyx.chat.turn.infra.emitter import get_default_emitter
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.context.search.models import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.okta_profile.okta_profile_tool import (
    OktaProfileTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool


# =============================================================================
# Helper Functions and Base Classes for DRY Principles
# =============================================================================


def create_fake_usage() -> Usage:
    """Create a standard fake usage object."""
    return Usage(
        requests=1,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
    )


def create_fake_response_usage() -> ResponseUsage:
    """Create a standard fake response usage object."""
    return ResponseUsage(
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
    )


def create_fake_message(
    text: str = "fake response", include_tool_calls: bool = False
) -> ResponseOutputMessage:
    """Create a fake response message with optional tool calls."""
    content = [ResponseOutputText(text=text, type="output_text", annotations=[])]
    message = ResponseOutputMessage(
        id="fake-message-id",
        role="assistant",
        content=content,  # type: ignore[arg-type]
        status="completed",
        type="message",
    )
    return message


def create_fake_response(
    response_id: str = "fake-response-id", message: ResponseOutputMessage | None = None
) -> Response:
    """Create a fake response object."""
    if message is None:
        message = create_fake_message()

    return Response(
        id=response_id,
        created_at=1234567890,
        object="response",
        output=[message],
        usage=create_fake_response_usage(),
        status="completed",
        model="fake-model",
        parallel_tool_calls=False,
        tool_choice="none",
        tools=[],
    )


class BaseFakeModel(Model):
    """Base class for fake models with common functionality."""

    def __init__(
        self, name: str = "fake-model", provider: str = "fake-provider", **kwargs: Any
    ) -> None:
        self.name = name
        self.provider = provider
        # Store any additional kwargs for subclasses
        self._kwargs = kwargs

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
        """Default get_response implementation."""
        message = create_fake_message()
        usage = create_fake_usage()
        return ModelResponse(
            output=[message], usage=usage, response_id="fake-response-id"
        )


class StreamableFakeModel(BaseFakeModel):
    """Base class for fake models that support streaming."""

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
        """Default streaming implementation."""
        return self._create_stream_events()

    def _create_stream_events(
        self,
        message: ResponseOutputMessage | None = None,
        response_id: str = "fake-response-id",
    ) -> AsyncIterator[object]:
        """Create standard stream events."""

        async def _gen() -> AsyncIterator[object]:  # type: ignore[misc]
            # Create message if not provided
            msg = message if message is not None else create_fake_message()

            final_response = create_fake_response(response_id, msg)

            # 1) created
            yield ResponseCreatedEvent(
                response=final_response, sequence_number=1, type="response.created"
            )

            # 2) stream some text (delta)
            for _ in range(5):
                yield ResponseTextDeltaEvent(
                    content_index=0,
                    delta="fake response",
                    item_id="fake-item-id",
                    logprobs=[],
                    output_index=0,
                    sequence_number=2,
                    type="response.output_text.delta",
                )

            # 3) completed
            yield ResponseCompletedEvent(
                response=final_response, sequence_number=3, type="response.completed"
            )

        return _gen()


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
    sample_messages: list[dict],
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


class FakeLLM(LLM):
    """Simple fake LLM implementation for testing."""

    def __init__(self) -> None:
        self._config = LLMConfig(
            model_provider="fake",
            model_name="fake-model",
            temperature=0.7,
            max_input_tokens=4096,
        )

    @property
    def config(self) -> LLMConfig:
        """Return the LLM configuration."""
        return self._config

    def log_model_configs(self) -> None:
        """Fake log_model_configs method."""

    def _invoke_implementation(
        self,
        prompt: Any,
        tools: Any = None,
        tool_choice: Any = None,
        structured_response_format: Any = None,
        timeout_override: Any = None,
        max_tokens: Any = None,
    ) -> Any:
        """Fake _invoke_implementation method."""
        from langchain_core.messages import AIMessage

        return AIMessage(content="fake response")

    def _stream_implementation(
        self,
        prompt: Any,
        tools: Any = None,
        tool_choice: Any = None,
        structured_response_format: Any = None,
        timeout_override: Any = None,
        max_tokens: Any = None,
    ) -> Any:
        """Fake _stream_implementation method that yields no messages."""
        return iter([])


class FakeModel(StreamableFakeModel):
    """Simple fake Model implementation for testing Agents SDK."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._output_schema: AgentOutputSchemaBase | None = None

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
        """Override to handle structured output properly."""
        # Store output_schema for streaming
        self._output_schema = output_schema

        # If there's an output schema, return JSON that matches it
        if output_schema is not None:
            # Return a message with JSON content that matches the schema
            message = create_fake_message(text='{"ready_to_answer": true}')
        else:
            message = create_fake_message()

        usage = create_fake_usage()
        return ModelResponse(
            output=[message], usage=usage, response_id="fake-response-id"
        )

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
        """Override streaming to handle structured output."""
        # Store output_schema for streaming
        self._output_schema = output_schema

        # If there's an output schema, create a message with JSON
        if output_schema is not None:
            message = create_fake_message(text='{"ready_to_answer": true}')
        else:
            message = create_fake_message()

        return self._create_stream_events(message=message)


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


class FakeSession:
    """Simple fake SQLAlchemy Session for testing."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def add(self, instance: Any) -> None:
        pass

    def flush(self) -> None:
        pass

    def query(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        return FakeQuery()

    def execute(self, *args: Any, **kwargs: Any) -> "FakeResult":
        return FakeResult()


class FakeQuery:
    """Simple fake SQLAlchemy Query for testing."""

    def filter(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        return self

    def first(self) -> Any:
        # Return a fake chat message to avoid the "Chat message with id not found" error
        class FakeChatMessage:
            def __init__(self) -> None:
                self.id = 123
                self.chat_session_id = "fake-session-id"
                self.message = "fake message"
                self.message_type = "user"
                self.token_count = 0
                self.rephrased_query = None
                self.citations: dict[str, Any] = {}
                self.error = None
                self.alternate_assistant_id = None
                self.overridden_model = None
                self.research_type = "FAST"
                self.research_plan: dict[str, Any] = {}
                self.final_documents: list[Any] = []
                self.research_answer_purpose = "ANSWER"
                self.parent_message = None
                self.is_agentic = False
                self.search_docs: list[Any] = []

        return FakeChatMessage()

    def all(self) -> list:
        return []


class FakeResult:
    """Simple fake SQLAlchemy Result for testing."""

    def scalar(self) -> Any:
        return None

    def fetchall(self) -> list:
        return []


class FakeRedis:
    """Simple fake Redis client for testing."""

    def __init__(self) -> None:
        self.data: dict = {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: Any, ex: Any = None) -> None:
        self.data[key] = value

    def delete(self, key: str) -> int:
        return self.data.pop(key, 0)

    def exists(self, key: str) -> bool:
        return key in self.data


@pytest.fixture
def fake_llm() -> LLM:
    """Fixture providing a fake LLM implementation."""
    return FakeLLM()


@pytest.fixture
def fake_model() -> Model:
    """Fixture providing a fake Model implementation."""
    return FakeModel()


@pytest.fixture
def fake_db_session() -> FakeSession:
    """Fixture providing a fake database session."""
    return FakeSession()


@pytest.fixture
def fake_redis_client() -> FakeRedis:
    """Fixture providing a fake Redis client."""
    return FakeRedis()


@pytest.fixture
def fake_tools() -> list[FunctionTool]:
    """Fixture providing a list of fake tools."""
    return []


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
def chat_turn_dependencies(
    fake_llm: LLM,
    fake_model: Model,
    fake_db_session: FakeSession,
    fake_tools: list[FunctionTool],
    fake_redis_client: FakeRedis,
) -> ChatTurnDependencies:
    """Fixture providing a complete ChatTurnDependencies object with fake implementations."""
    emitter = get_default_emitter()
    return ChatTurnDependencies(
        llm_model=fake_model,
        model_settings=ModelSettings(temperature=0.0, include_usage=True),
        llm=fake_llm,
        db_session=fake_db_session,  # type: ignore[arg-type]
        tools=fake_tools,
        redis_client=fake_redis_client,  # type: ignore[arg-type]
        emitter=emitter,
        search_pipeline=Mock(SearchTool),
        image_generation_tool=Mock(ImageGenerationTool),
        okta_profile_tool=Mock(OktaProfileTool),
    )


@pytest.fixture
def fake_failing_model() -> Model:
    return FakeFailingModel()


@pytest.fixture
def fake_tool_call_model() -> Model:
    return FakeToolCallModel()


@pytest.fixture
def sample_messages() -> list[dict]:
    """Fixture providing sample messages for testing."""
    return [
        {"role": "user", "content": "Hello, how are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you!"},
    ]


def test_fast_chat_turn_basic(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[dict],
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
    sample_messages: list[dict],
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
    sample_messages: list[dict],
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
    sample_messages: list[dict],
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


class FakeCitationModel(StreamableFakeModel):
    """Fake model that simulates having iteration answers with cited documents."""

    def __init__(
        self, iteration_answers: list[IterationAnswer] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._iteration_answers = iteration_answers or []

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
        """Override to create a response that includes citations."""
        # Create a message with citations that reference our test documents
        message = create_fake_message(
            text="Based on the search results, here's the answer with citations [[1]]."
        )
        usage = create_fake_usage()
        return ModelResponse(
            output=[message], usage=usage, response_id="fake-response-id"
        )


class FakeCitationModelWithContext(StreamableFakeModel):
    def __init__(
        self, iteration_answers: list[IterationAnswer] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._iteration_answers = iteration_answers or []

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
        """Override to create a response that includes citations."""
        # If there's an output schema, return JSON that matches it
        if output_schema is not None:
            message = create_fake_message(text='{"ready_to_answer": true}')
        else:
            # Create a message with citations that reference our test documents
            message = create_fake_message(
                text="Based on the search results, here's the answer with citations [[1]]."
            )
        usage = create_fake_usage()
        return ModelResponse(
            output=[message], usage=usage, response_id="fake-response-id"
        )

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
        """Override streaming to handle structured output."""
        # If there's an output schema, create a message with JSON
        if output_schema is not None:
            message = create_fake_message(text='{"ready_to_answer": true}')
            return self._create_stream_events(message=message)
        else:
            # For non-structured output, use the citation text
            return super().stream_response(
                system_instructions,
                input,
                model_settings,
                tools,
                output_schema,
                handoffs,
                tracing,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                prompt=prompt,
            )

    def _create_stream_events(
        self,
        message: ResponseOutputMessage | None = None,
        response_id: str = "fake-response-id",
    ) -> AsyncIterator[object]:
        """Create stream events with citation text."""
        from openai.types.responses.response_stream_event import (
            ResponseContentPartAddedEvent,
        )
        from openai.types.responses.response_stream_event import (
            ResponseContentPartDoneEvent,
        )

        async def _gen() -> AsyncIterator[object]:  # type: ignore[misc]
            # Use the provided message if available, otherwise use citation text
            if message is not None:
                msg = message
                citation_text = "hi"
            else:
                # Create message with citation text
                citation_text = "Based on the search results, here's the answer with citations [[1]](https://example.com)."
                msg = create_fake_message(text=citation_text)

            final_response = create_fake_response(response_id, msg)

            # 1) created
            yield ResponseCreatedEvent(
                response=final_response, sequence_number=1, type="response.created"
            )

            # 2) content_part.added - this triggers MessageStart
            yield ResponseContentPartAddedEvent(
                content_index=0,
                item_id="fake-item-id",
                output_index=0,
                part=ResponseOutputText(text="", type="output_text", annotations=[]),
                sequence_number=2,
                type="response.content_part.added",
            )

            # 3) stream the citation text in chunks
            words = citation_text.split()
            for word in words:
                yield ResponseTextDeltaEvent(
                    content_index=0,
                    delta=word + " ",
                    item_id="fake-item-id",
                    logprobs=[],
                    output_index=0,
                    sequence_number=3,
                    type="response.output_text.delta",
                )

            # 4) content_part.done - this triggers SectionEnd for the message
            yield ResponseContentPartDoneEvent(
                content_index=0,
                item_id="fake-item-id",
                output_index=0,
                part=ResponseOutputText(
                    text=citation_text, type="output_text", annotations=[]
                ),
                sequence_number=4,
                type="response.content_part.done",
            )

            # 5) completed
            yield ResponseCompletedEvent(
                response=final_response, sequence_number=5, type="response.completed"
            )

        return _gen()


def test_fast_chat_turn_citation_processing(
    chat_turn_dependencies: ChatTurnDependencies,
    sample_messages: list[dict],
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    """Test that citation processing works correctly when iteration answers contain cited documents.

    This test verifies that when the agent has access to context documents through
    iteration answers, citations in the final answer are properly processed and
    citation events are emitted. It uses the _fast_chat_turn_core function with
    dependency injection instead of mocking.
    """
    from datetime import datetime
    from onyx.chat.turn.fast_chat_turn import _fast_chat_turn_core
    from onyx.chat.turn.infra.chat_turn_event_stream import unified_event_stream
    from onyx.server.query_and_chat.streaming_models import MessageStart

    # Create a fake inference section with cited documents
    fake_chunk = InferenceChunk(
        chunk_id=1,
        document_id="test-doc-1",
        source_type=DocumentSource.WEB,
        semantic_identifier="Test Document",
        title="Test Document Title",
        content="This is test content for citation processing.",
        blurb="Test blurb",
        source_links={0: "https://example.com/test-doc"},
        match_highlights=[],
        updated_at=datetime.now(),
        metadata={},
        boost=1,
        recency_bias=0.0,
        score=0.9,
        hidden=False,
        doc_summary="Test document summary",
        chunk_context="Test context",
        section_continuation=False,
        image_file_id=None,
    )

    fake_inference_section = InferenceSection(
        center_chunk=fake_chunk,
        chunks=[fake_chunk],
        combined_content="This is test content for citation processing.",
    )

    # Create a fake iteration answer with cited documents
    fake_iteration_answer = IterationAnswer(
        tool="internal_search",
        tool_id=1,
        iteration_nr=1,
        parallelization_nr=1,
        question="What is test content?",
        reasoning="Need to search for test content",
        answer="The test content is about citation processing [[1]].",
        cited_documents={1: fake_inference_section},
    )

    # Create a custom model that simulates having iteration answers
    citation_model = FakeCitationModelWithContext(
        iteration_answers=[fake_iteration_answer]
    )
    chat_turn_dependencies.llm_model = citation_model

    # Create a fake prompt config
    prompt_config = PromptConfig(
        system_prompt="You are a helpful assistant.",
        task_prompt="Answer the user's question.",
        datetime_aware=False,
    )

    # Create a decorated version of _fast_chat_turn_core for testing
    @unified_event_stream
    def test_fast_chat_turn_core(
        messages: list[dict],
        dependencies: ChatTurnDependencies,
        session_id: UUID,
        msg_id: int,
        res_type: ResearchType,
        p_config: PromptConfig,
    ) -> None:
        # Manually populate cited_documents from the iteration answer for this test
        # In real usage, cited_documents would be populated by the tool implementations
        context_docs = list(fake_iteration_answer.cited_documents.values())

        _fast_chat_turn_core(
            messages,
            dependencies,
            session_id,
            msg_id,
            res_type,
            p_config,
            starter_global_iteration_responses=[fake_iteration_answer],
            starter_cited_documents=context_docs,
        )

    # Run the test with the core function
    generator = test_fast_chat_turn_core(
        sample_messages,
        chat_turn_dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
    )
    packets = list(generator)

    # Verify we get the expected packets including citation events
    assert_packets_contain_stop(packets)

    # Look for message start and citation events in the packets
    message_start_found = False
    message_start_has_final_docs = False
    citation_start_found = False
    citation_delta_found = False
    citation_section_end_found = False
    message_start_index = None
    citation_start_index = None
    message_delta_index = None

    for packet in packets:
        if isinstance(packet.obj, MessageStart):
            message_start_found = True
            message_start_index = packet.ind
            # Verify that final_documents is populated with cited documents
            if (
                packet.obj.final_documents is not None
                and len(packet.obj.final_documents) > 0
            ):
                message_start_has_final_docs = True
                # Verify the document ID matches our test document
                assert packet.obj.final_documents[0].document_id == "test-doc-1"
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
        elif packet.obj.type == "message_delta" and message_delta_index is None:
            # Track the first message delta index
            message_delta_index = packet.ind

    # Verify all expected events were emitted
    assert message_start_found, "MessageStart event should be emitted"
    assert (
        message_start_has_final_docs
    ), "MessageStart should contain final_documents with cited docs"
    assert citation_start_found, "CitationStart event should be emitted"
    assert citation_delta_found, "CitationDelta event should be emitted"
    assert citation_section_end_found, "Citation section should end with SectionEnd"

    # Verify that citation packets are emitted after message packets (higher index)
    assert message_start_index is not None, "message_start_index should be set"
    assert citation_start_index is not None, "citation_start_index should be set"
    assert (
        citation_start_index > message_start_index
    ), f"Citation packets (index {citation_start_index}) > message start (index {message_start_index})"
