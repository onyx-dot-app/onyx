"""Tests for SearchTool.run_v2() using dependency injection via search_pipeline_override_for_testing.

This test module focuses on testing the SearchTool.run_v2() method directly,
using the search_pipeline_override_for_testing parameter for dependency injection
instead of using mocks.
"""

from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.models import PromptConfig
from onyx.chat.turn.models import ChatTurnContext
from onyx.context.search.enums import SearchType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceSection
from onyx.server.query_and_chat.streaming_models import SavedSearchDoc
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from tests.unit.onyx.chat.turn.utils import create_test_inference_chunk
from tests.unit.onyx.chat.turn.utils import FakeQuery
from tests.unit.onyx.chat.turn.utils import FakeRedis
from tests.unit.onyx.chat.turn.utils import FakeResult


# =============================================================================
# Fake Classes for Dependency Injection
# =============================================================================


def create_fake_database_session() -> Any:
    """Create a fake SQLAlchemy Session for testing"""
    from unittest.mock import Mock
    from sqlalchemy.orm import Session

    # Create a mock that behaves like a real Session
    fake_session = Mock(spec=Session)
    fake_session.committed = False
    fake_session.rolled_back = False

    def mock_commit() -> None:
        fake_session.committed = True

    def mock_rollback() -> None:
        fake_session.rolled_back = True

    fake_session.commit = mock_commit
    fake_session.rollback = mock_rollback
    fake_session.add = Mock()
    fake_session.flush = Mock()
    fake_session.query = Mock(return_value=FakeQuery())
    fake_session.execute = Mock(return_value=FakeResult())

    return fake_session


class FakeSearchQuery:
    """Fake SearchQuery for testing"""

    def __init__(self) -> None:
        self.search_type = SearchType.SEMANTIC
        self.filters = IndexFilters(access_control_list=None)
        self.recency_bias_multiplier = 1.0


class FakeSearchPipeline:
    """Fake SearchPipeline for dependency injection in SearchTool"""

    def __init__(self, sections: list[InferenceSection] | None = None) -> None:
        self.sections = sections or []
        self.search_query = FakeSearchQuery()

    @property
    def merged_retrieved_sections(self) -> list[InferenceSection]:
        return self.sections

    @property
    def final_context_sections(self) -> list[InferenceSection]:
        return self.sections

    @property
    def section_relevance(self) -> list | None:
        return None


class FakeLLMConfig:
    """Fake LLM config for testing"""

    def __init__(self) -> None:
        self.max_input_tokens = 128000  # Default GPT-4 context
        self.model_name = "gpt-4"
        self.model_provider = "openai"


class FakeLLM:
    """Fake LLM for testing"""

    def __init__(self) -> None:
        self.config = FakeLLMConfig()

    def log_model_configs(self) -> None:
        pass


class FakePersona:
    """Fake Persona for testing"""

    def __init__(self) -> None:
        self.id = 1
        self.name = "Test Persona"
        self.chunks_above = None
        self.chunks_below = None
        self.llm_relevance_filter = False
        self.llm_filter_extraction = False
        self.recency_bias = "auto"
        self.prompt_ids = []
        self.document_sets = []
        self.num_chunks = None
        self.llm_model_version_override = None


class FakeUser:
    """Fake User for testing"""

    def __init__(self) -> None:
        self.id = 1
        self.email = "test@example.com"


class FakeEmitter:
    """Fake emitter for testing that records all emitted packets"""

    def __init__(self) -> None:
        self.packet_history: list[Any] = []

    def emit(self, packet: Any) -> None:
        self.packet_history.append(packet)


class FakeRunDependencies:
    """Fake run dependencies for testing"""

    def __init__(
        self, db_session: Any, redis_client: FakeRedis, search_tool: SearchTool
    ) -> None:
        self.db_session = db_session
        self.redis_client = redis_client
        self.emitter = FakeEmitter()
        self.tools = [search_tool]

    def get_prompt_config(self) -> PromptConfig:
        return PromptConfig(
            default_behavior_system_prompt="You are a helpful assistant.",
            reminder="Answer the user's question.",
            custom_instructions="",
            datetime_aware=False,
        )


# =============================================================================
# Test Helper Functions
# =============================================================================


def create_search_section_with_semantic_id(
    document_id: str, semantic_identifier: str, content: str, link: str
) -> InferenceSection:
    """Create a test inference section with custom semantic_identifier"""
    chunk = create_test_inference_chunk(
        document_id=document_id,
        semantic_identifier=semantic_identifier,
        content=content,
        link=link,
    )
    return InferenceSection(
        center_chunk=chunk,
        chunks=[chunk],
        combined_content=content,
    )


def create_fake_search_pipeline_with_results(
    sections: list[InferenceSection] | None = None,
) -> FakeSearchPipeline:
    """Create a fake search pipeline with test results"""
    if sections is None:
        sections = [
            create_search_section_with_semantic_id(
                document_id="doc1",
                semantic_identifier="test_doc_1",
                content="First test document content",
                link="https://example.com/doc1",
            ),
            create_search_section_with_semantic_id(
                document_id="doc2",
                semantic_identifier="test_doc_2",
                content="Second test document content",
                link="https://example.com/doc2",
            ),
        ]

    return FakeSearchPipeline(sections=sections)


def create_search_tool_with_fake_pipeline(
    search_pipeline: FakeSearchPipeline,
    db_session: Any | None = None,
    tool_id: int = 1,
) -> SearchTool:
    """Create a SearchTool instance with a fake search pipeline for testing"""
    from onyx.chat.models import AnswerStyleConfig
    from onyx.chat.models import CitationConfig
    from onyx.chat.models import DocumentPruningConfig
    from onyx.context.search.enums import LLMEvaluationType

    fake_db_session = db_session or create_fake_database_session()
    fake_llm = FakeLLM()
    fake_persona = FakePersona()
    fake_user = FakeUser()

    return SearchTool(
        tool_id=tool_id,
        db_session=fake_db_session,
        user=fake_user,  # type: ignore
        persona=fake_persona,  # type: ignore
        retrieval_options=None,
        prompt_config=PromptConfig(
            default_behavior_system_prompt="You are a helpful assistant.",
            reminder="Answer the user's question.",
            custom_instructions="",
            datetime_aware=False,
        ),
        llm=fake_llm,  # type: ignore
        fast_llm=fake_llm,  # type: ignore
        evaluation_type=LLMEvaluationType.SKIP,
        answer_style_config=AnswerStyleConfig(citation_config=CitationConfig()),
        document_pruning_config=DocumentPruningConfig(),
        search_pipeline_override_for_testing=search_pipeline,  # type: ignore
    )


def create_fake_run_context(
    chat_session_id: UUID,
    message_id: int,
    db_session: Any,
    redis_client: FakeRedis,
    search_tool: SearchTool,
) -> RunContextWrapper[ChatTurnContext]:
    """Create a fake run context for testing"""
    run_dependencies = FakeRunDependencies(db_session, redis_client, search_tool)

    context = ChatTurnContext(
        chat_session_id=chat_session_id,
        message_id=message_id,
        run_dependencies=run_dependencies,  # type: ignore
    )

    return RunContextWrapper(context=context)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def chat_session_id() -> UUID:
    """Fixture providing fake chat session ID."""
    return uuid4()


@pytest.fixture
def message_id() -> int:
    """Fixture providing fake message ID."""
    return 123


@pytest.fixture
def research_type() -> ResearchType:
    """Fixture providing fake research type."""
    return ResearchType.FAST


@pytest.fixture
def fake_db_session() -> Any:
    """Fixture providing a fake database session."""
    return create_fake_database_session()


@pytest.fixture
def fake_redis_client() -> FakeRedis:
    """Fixture providing a fake Redis client."""
    return FakeRedis()


@pytest.fixture
def fake_search_pipeline() -> FakeSearchPipeline:
    """Fixture providing a fake search pipeline with default test results."""
    return create_fake_search_pipeline_with_results()


@pytest.fixture
def search_tool(
    fake_search_pipeline: FakeSearchPipeline, fake_db_session: Any
) -> SearchTool:
    """Fixture providing a SearchTool with fake search pipeline."""
    return create_search_tool_with_fake_pipeline(fake_search_pipeline, fake_db_session)


@pytest.fixture
def fake_run_context(
    chat_session_id: UUID,
    message_id: int,
    fake_db_session: Any,
    fake_redis_client: FakeRedis,
    search_tool: SearchTool,
) -> RunContextWrapper[ChatTurnContext]:
    """Fixture providing a complete RunContextWrapper with fake implementations."""
    return create_fake_run_context(
        chat_session_id, message_id, fake_db_session, fake_redis_client, search_tool
    )


# =============================================================================
# Test Functions
# =============================================================================


def test_search_tool_run_v2_basic_functionality(
    fake_run_context: RunContextWrapper[ChatTurnContext],
    search_tool: SearchTool,
    fake_db_session: Any,
) -> None:
    """Test basic functionality of SearchTool.run_v2() using dependency injection.

    This test mirrors the original test_internal_search_core_basic_functionality but
    uses the run_v2 method with search_pipeline_override_for_testing instead of mocks.
    """
    from unittest.mock import patch

    # Arrange
    query = "test search query"

    # Create a session context manager
    class FakeSessionContextManager:
        def __enter__(self) -> Any:
            return fake_db_session

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    # Act - patch get_session_with_current_tenant to return our fake session
    with patch(
        "onyx.tools.tool_implementations.search.search_tool.get_session_with_current_tenant",
        return_value=FakeSessionContextManager(),
    ):
        result = search_tool.run_v2(fake_run_context, query=query)

    # Assert - verify result is a JSON string
    import json

    result_list = json.loads(result)
    assert isinstance(result_list, list)
    assert len(result_list) == 2

    # Verify result contains InternalSearchResult objects (as dicts in JSON)
    assert result_list[0]["unique_identifier_to_strip_away"] == "doc1"
    assert result_list[0]["title"] == "test_doc_1"
    assert result_list[0]["excerpt"] == "First test document content"
    assert result_list[0]["document_citation_number"] == -1

    assert result_list[1]["unique_identifier_to_strip_away"] == "doc2"
    assert result_list[1]["title"] == "test_doc_2"
    assert result_list[1]["excerpt"] == "Second test document content"
    assert result_list[1]["document_citation_number"] == -1

    # Verify context was updated (decorator increments current_run_step)
    assert fake_run_context.context.current_run_step == 2
    assert len(fake_run_context.context.iteration_instructions) == 1
    assert len(fake_run_context.context.global_iteration_responses) == 1

    # Verify fetched_documents_cache was populated
    assert len(fake_run_context.context.fetched_documents_cache) == 2
    assert "doc1" in fake_run_context.context.fetched_documents_cache
    assert "doc2" in fake_run_context.context.fetched_documents_cache

    # Verify cache entries have correct structure
    cache_entry_1 = fake_run_context.context.fetched_documents_cache["doc1"]
    assert cache_entry_1.document_citation_number == -1
    assert cache_entry_1.inference_section is not None
    assert cache_entry_1.inference_section.center_chunk.document_id == "doc1"

    cache_entry_2 = fake_run_context.context.fetched_documents_cache["doc2"]
    assert cache_entry_2.document_citation_number == -1
    assert cache_entry_2.inference_section.center_chunk.document_id == "doc2"

    # Check iteration instruction
    instruction = fake_run_context.context.iteration_instructions[0]
    assert isinstance(instruction, IterationInstructions)
    assert instruction.iteration_nr == 1
    assert instruction.purpose == "Searching internally for information"
    assert (
        "I am now using Internal Search to gather information on"
        in instruction.reasoning
    )

    # Check iteration answer
    answer = fake_run_context.context.global_iteration_responses[0]
    assert isinstance(answer, IterationAnswer)
    assert answer.tool == SearchTool.__name__
    assert answer.tool_id == search_tool.id
    assert answer.iteration_nr == 1
    assert answer.answer == ""
    assert len(answer.cited_documents) == 2

    # Verify emitter events were captured
    emitter = fake_run_context.context.run_dependencies.emitter
    # Should have: SearchToolStart, SearchToolDelta (query), SearchToolDelta (docs)
    assert len(emitter.packet_history) >= 3

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, SearchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SearchToolDelta)

    # Check the first SearchToolDelta (query)
    first_delta = emitter.packet_history[1].obj
    assert first_delta.queries == [query]
    assert first_delta.documents == []

    # Check the second SearchToolDelta (documents)
    second_delta = emitter.packet_history[2].obj
    assert second_delta.queries == []
    assert len(second_delta.documents) == 2

    # Verify the SavedSearchDoc objects
    first_doc = second_delta.documents[0]
    assert isinstance(first_doc, SavedSearchDoc)
    assert first_doc.document_id == "doc1"
    assert first_doc.semantic_identifier == "test_doc_1"
