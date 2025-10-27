"""
Shared test utilities for fast_chat_turn tests.

This module contains fake implementations of dependencies used in fast_chat_turn
tests, following dependency injection patterns.
"""

from collections.abc import AsyncIterator
from typing import Any
from typing import List
from uuid import UUID

import pytest
from agents import AgentOutputSchemaBase
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
from openai.types.responses.response_stream_event import ResponseCompletedEvent
from openai.types.responses.response_stream_event import ResponseCreatedEvent
from openai.types.responses.response_stream_event import ResponseTextDeltaEvent
from openai.types.responses.response_usage import InputTokensDetails
from openai.types.responses.response_usage import OutputTokensDetails
from openai.types.responses.response_usage import ResponseUsage

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.chat.turn.infra.emitter import get_default_emitter
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.tools.tool import Tool as OnyxTool


# =============================================================================
# Fake LLM Implementation
# =============================================================================


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


# =============================================================================
# Fake Model Implementations
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


class FakeModelConfig:
    """Fake config object for fake models."""

    def __init__(
        self, model_name: str = "fake-model", model_provider: str = "fake-provider"
    ) -> None:
        self.model_name = model_name
        self.model_provider = model_provider


class BaseFakeModel(Model):
    """Base class for fake models with common functionality."""

    def __init__(
        self, name: str = "fake-model", provider: str = "fake-provider", **kwargs: Any
    ) -> None:
        self.name = name
        self.provider = provider
        # Add config attribute for compatibility with save_turn
        self.config = FakeModelConfig(model_name=name, model_provider=provider)
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


# =============================================================================
# Helper Functions for Creating Custom Models
# =============================================================================


def get_model_with_response(
    response_text: str, stream_word_by_word: bool = True
) -> Model:
    """Create a fake model that returns a specific response text.

    This is useful for testing scenarios where you need a model to return
    specific content (e.g., responses with citations).

    Args:
        response_text: The text that the model should return in its response
        stream_word_by_word: If True, stream the response word by word with spaces.
            If False, use the default streaming behavior (single delta).

    Returns:
        A Model instance that returns the specified response text
    """

    class CustomResponseModel(StreamableFakeModel):
        """Fake model that returns a custom response text."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._response_text = response_text
            self._stream_word_by_word = stream_word_by_word

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
            """Override to create a response with custom text."""
            # If there's an output schema, return JSON that matches it
            if output_schema is not None:
                message = create_fake_message(text='{"ready_to_answer": true}')
            else:
                # Create a message with the custom response text
                message = create_fake_message(text=self._response_text)
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
            """Override streaming to use custom text."""
            # If there's an output schema, use default streaming
            if output_schema is not None:
                return self._create_stream_events()
            else:
                # For non-structured output, use the custom text
                return self._create_custom_stream_events()

        def _create_custom_stream_events(self) -> AsyncIterator[object]:
            """Create stream events with custom response text."""
            from openai.types.responses.response_stream_event import (
                ResponseContentPartAddedEvent,
            )
            from openai.types.responses.response_stream_event import (
                ResponseContentPartDoneEvent,
            )

            async def _gen() -> AsyncIterator[object]:  # type: ignore[misc]
                msg = create_fake_message(text=self._response_text)
                final_response = create_fake_response(
                    response_id="fake-response-id", message=msg
                )

                # 1) created
                yield ResponseCreatedEvent(
                    response=final_response, sequence_number=1, type="response.created"
                )

                # 2) content_part.added - this triggers MessageStart
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

                # 3) stream the text
                if self._stream_word_by_word:
                    # Stream word by word with spaces
                    words = self._response_text.split()
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
                else:
                    # Stream the entire text at once
                    yield ResponseTextDeltaEvent(
                        content_index=0,
                        delta=self._response_text,
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
                        text=self._response_text, type="output_text", annotations=[]
                    ),
                    sequence_number=4,
                    type="response.content_part.done",
                )

                # 5) completed
                yield ResponseCompletedEvent(
                    response=final_response,
                    sequence_number=5,
                    type="response.completed",
                )

            return _gen()

    return CustomResponseModel()


# =============================================================================
# Fake Database Session
# =============================================================================


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


# =============================================================================
# Fake Redis Client
# =============================================================================


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


# =============================================================================
# Pytest Fixtures
# =============================================================================


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
def fake_tools() -> list[OnyxTool]:
    """Fixture providing a list of fake tools."""
    return []


@pytest.fixture
def chat_turn_dependencies(
    fake_llm: LLM,
    fake_model: Model,
    fake_db_session: FakeSession,
    fake_tools: list[OnyxTool],
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
    )


# =============================================================================
# Citation Test Helpers
# =============================================================================


def create_test_inference_chunk(
    chunk_id: int = 1,
    document_id: str = "test-doc-1",
    semantic_identifier: str = "Test Document",
    title: str = "Test Document Title",
    content: str = "This is test content for citation processing.",
    link: str = "https://example.com/test-doc",
) -> Any:
    """Create a fake InferenceChunk for testing citations."""
    from datetime import datetime

    from onyx.context.search.models import DocumentSource
    from onyx.context.search.models import InferenceChunk

    return InferenceChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        source_type=DocumentSource.WEB,
        semantic_identifier=semantic_identifier,
        title=title,
        content=content,
        blurb="Test blurb",
        source_links={0: link},
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


def create_test_inference_section(
    chunk_id: int = 1,
    document_id: str = "test-doc-1",
    content: str = "This is test content for citation processing.",
    link: str = "https://example.com/test-doc",
) -> Any:
    """Create a fake InferenceSection for testing citations."""
    from onyx.context.search.models import InferenceSection

    fake_chunk = create_test_inference_chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        content=content,
        link=link,
    )

    return InferenceSection(
        center_chunk=fake_chunk,
        chunks=[fake_chunk],
        combined_content=content,
    )


def create_test_iteration_answer(
    citation_num: int = 1,
    document_id: str = "test-doc-1",
    content: str = "This is test content for citation processing.",
    link: str = "https://example.com/test-doc",
    answer: str = "The test content is about citation processing [[1]].",
) -> Any:
    """Create a fake IterationAnswer with citations for testing."""
    from onyx.agents.agent_search.dr.models import IterationAnswer

    fake_section = create_test_inference_section(
        chunk_id=citation_num,
        document_id=document_id,
        content=content,
        link=link,
    )

    return IterationAnswer(
        tool="internal_search",
        tool_id=1,
        iteration_nr=1,
        parallelization_nr=1,
        question="What is test content?",
        reasoning="Need to search for test content",
        answer=answer,
        cited_documents={citation_num: fake_section},
    )


def create_test_llm_doc(
    document_id: str = "test-doc-1",
    content: str = "This is test content for citation processing.",
    semantic_identifier: str = "Test Document",
    link: str = "https://example.com/test-doc",
    document_citation_number: int = 1,
) -> Any:
    """Create a fake LlmDoc for testing citations."""
    from datetime import datetime

    from onyx.chat.models import LlmDoc
    from onyx.context.search.models import DocumentSource

    return LlmDoc(
        document_id=document_id,
        content=content,
        blurb="Test blurb",
        semantic_identifier=semantic_identifier,
        source_type=DocumentSource.WEB,
        metadata={},
        updated_at=datetime.now(),
        link=link,
        source_links={0: link},
        match_highlights=[],
        document_citation_number=document_citation_number,
    )


@pytest.fixture
def chat_turn_context(
    chat_turn_dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> ChatTurnContext:
    """Fixture providing a ChatTurnContext with filler arguments for testing."""
    from onyx.chat.turn.models import ChatTurnContext

    return ChatTurnContext(
        chat_session_id=chat_session_id,
        message_id=message_id,
        research_type=research_type,
        run_dependencies=chat_turn_dependencies,
    )
