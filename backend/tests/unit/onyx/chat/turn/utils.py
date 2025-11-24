"""
Shared test utilities for fast_chat_turn tests.

This module contains fake implementations of dependencies used in fast_chat_turn
tests, following dependency injection patterns.
"""

from typing import Any
from uuid import UUID

import pytest

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

    def _invoke_implementation_langchain(
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
        from onyx.llm.model_response import Choice
        from onyx.llm.model_response import Message
        from onyx.llm.model_response import ModelResponse as OnyxModelResponse

        return OnyxModelResponse(
            id="fake-id",
            created="0",
            choice=Choice(
                finish_reason="stop",
                index=0,
                message=Message(content="fake response", role="assistant"),
            ),
        )

    def _stream_implementation_langchain(
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
    fake_db_session: FakeSession,
    fake_tools: list[OnyxTool],
    fake_redis_client: FakeRedis,
) -> ChatTurnDependencies:
    """Fixture providing a complete ChatTurnDependencies object with fake implementations."""
    from onyx.chat.models import PromptConfig

    emitter = get_default_emitter()
    prompt_config = PromptConfig(
        default_behavior_system_prompt="You are a helpful assistant.",
        reminder="Answer the user's question.",
        custom_instructions="",
        datetime_aware=False,
    )
    return ChatTurnDependencies(
        llm=fake_llm,
        db_session=fake_db_session,  # type: ignore[arg-type]
        tools=fake_tools,
        redis_client=fake_redis_client,  # type: ignore[arg-type]
        emitter=emitter,
        user_or_none=None,
        prompt_config=prompt_config,
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
) -> ChatTurnContext:
    """Fixture providing a ChatTurnContext with filler arguments for testing."""
    from onyx.chat.turn.models import ChatTurnContext

    return ChatTurnContext(
        chat_session_id=chat_session_id,
        message_id=message_id,
        run_dependencies=chat_turn_dependencies,
    )
