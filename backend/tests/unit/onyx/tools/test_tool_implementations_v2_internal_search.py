from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.models import LlmDoc
from onyx.chat.turn.models import ChatTurnContext
from onyx.context.search.models import InferenceSection
from onyx.server.query_and_chat.streaming_models import SavedSearchDoc
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from tests.unit.onyx.chat.turn.utils import create_test_inference_chunk
from tests.unit.onyx.chat.turn.utils import create_test_inference_section
from tests.unit.onyx.chat.turn.utils import FakeQuery
from tests.unit.onyx.chat.turn.utils import FakeRedis
from tests.unit.onyx.chat.turn.utils import FakeResult


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


class FakeTool:
    """Mock Tool object for testing"""

    def __init__(self, tool_id: int = 1, name: str = SearchTool.__name__):
        self.id = tool_id
        self.name = name


class FakeSearchPipeline:
    """Fake search pipeline for dependency injection"""

    def __init__(
        self, responses: list | None = None, should_raise_exception: bool = False
    ) -> None:
        self.responses = responses or []
        self.should_raise_exception = should_raise_exception
        self.run_called = False
        self.run_kwargs: dict[str, Any] = {}

    def run(self, **kwargs: Any) -> list:
        self.run_called = True
        self.run_kwargs = kwargs
        if self.should_raise_exception:
            raise Exception("Test exception from search pipeline")
        return self.responses


class FakeSearchResponse:
    """Fake search response for testing"""

    def __init__(self, response_id: str, top_sections: list | None = None) -> None:
        self.id = response_id
        self.response = FakeSearchResponseSummary(top_sections or [])


class FakeSearchResponseSummary:
    """Fake search response summary for testing"""

    def __init__(self, top_sections: list) -> None:
        self.top_sections = top_sections


class FakeSessionContextManager:
    """Fake session context manager for testing"""

    def __init__(self, session: Any = None) -> None:
        self.session = session or create_fake_database_session()

    def __enter__(self) -> Any:
        return self.session

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


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
    sections: list | None = None, should_raise_exception: bool = False
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

    responses = [
        FakeSearchResponse(
            response_id=SEARCH_RESPONSE_SUMMARY_ID,
            top_sections=sections,
        ),
    ]

    return FakeSearchPipeline(
        responses=responses, should_raise_exception=should_raise_exception
    )


def create_fake_search_pipeline_empty() -> FakeSearchPipeline:
    """Create a fake search pipeline with no results"""
    return FakeSearchPipeline(responses=[])


def create_fake_search_pipeline_multiple_responses() -> FakeSearchPipeline:
    """Create a fake search pipeline with multiple responses"""
    test_sections = [create_test_inference_section()]
    responses = [
        FakeSearchResponse(response_id="other_response_id", top_sections=[]),
        FakeSearchResponse(
            response_id=SEARCH_RESPONSE_SUMMARY_ID,
            top_sections=test_sections,
        ),
        FakeSearchResponse(response_id="another_response_id", top_sections=[]),
    ]
    return FakeSearchPipeline(responses=responses)


def run_internal_search_core_with_dependencies(
    run_context: RunContextWrapper[ChatTurnContext],
    queries: list[str],
    search_pipeline: FakeSearchPipeline,
    session_context_manager: FakeSessionContextManager | None = None,
    redis_client: FakeRedis | None = None,
) -> list[LlmDoc]:
    """Helper function to run the real _internal_search_core with injected dependencies"""
    from unittest.mock import patch
    from onyx.tools.tool_implementations_v2.internal_search import _internal_search_core

    # Patch the dependencies that the real function uses
    with patch(
        "onyx.tools.tool_implementations_v2.internal_search.get_session_with_current_tenant"
    ) as mock_get_session, patch(
        "onyx.tools.tool_implementations_v2.internal_search.get_tool_by_name"
    ) as mock_get_tool_by_name:

        # Set up the session context manager mock
        if session_context_manager:
            mock_get_session.return_value = session_context_manager
        else:
            mock_get_session.return_value = FakeSessionContextManager()

        # Set up the get_tool_by_name mock to return our fake tool
        mock_get_tool_by_name.return_value = FakeTool()

        # Set up the Redis client in the run context if provided
        if redis_client:
            run_context.context.run_dependencies.redis_client = redis_client  # type: ignore

        # Call the real _internal_search_core function
        return _internal_search_core(run_context, queries, search_pipeline)  # type: ignore[arg-type]


class FakeSearchToolOverrideKwargs:
    """Fake search tool override kwargs for testing"""

    def __init__(
        self,
        force_no_rerank: bool = True,
        alternate_db_session: Any = None,
        skip_query_analysis: bool = True,
        original_query: str | None = None,
    ) -> None:
        self.force_no_rerank = force_no_rerank
        self.alternate_db_session = alternate_db_session
        self.skip_query_analysis = skip_query_analysis
        self.original_query = original_query


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
def fake_run_context(
    chat_turn_context: ChatTurnContext,
) -> RunContextWrapper[ChatTurnContext]:
    """Fixture providing a complete RunContextWrapper with fake implementations."""
    return RunContextWrapper(context=chat_turn_context)


@pytest.fixture
def fake_search_pipeline() -> FakeSearchPipeline:
    """Fixture providing a fake search pipeline."""
    return create_fake_search_pipeline_with_results()


@pytest.fixture
def fake_session_context_manager() -> FakeSessionContextManager:
    """Fixture providing a fake session context manager."""
    return FakeSessionContextManager()


# =============================================================================
# Test Functions
# =============================================================================


def test_internal_search_core_basic_functionality(
    fake_run_context: RunContextWrapper[ChatTurnContext],
    fake_session_context_manager: FakeSessionContextManager,
) -> None:
    """Test basic functionality of _internal_search_core function using dependency injection"""
    # Arrange
    query = "test search query"
    queries = [query]
    test_pipeline = create_fake_search_pipeline_with_results()

    # Act
    result = run_internal_search_core_with_dependencies(
        fake_run_context, queries, test_pipeline, fake_session_context_manager
    )

    # Assert
    assert isinstance(result, list)
    assert len(result) == 2
    # Verify result contains LlmDoc objects
    assert all(isinstance(doc, LlmDoc) for doc in result)
    assert result[0].document_id == "doc1"
    assert result[0].semantic_identifier == "test_doc_1"
    assert result[0].content == "First test document content"
    assert result[1].document_id == "doc2"
    assert result[1].semantic_identifier == "test_doc_2"
    assert result[1].content == "Second test document content"

    # Verify context was updated (decorator increments current_run_step)
    assert fake_run_context.context.current_run_step == 2
    assert len(fake_run_context.context.iteration_instructions) == 1
    assert (
        len(fake_run_context.context.aggregated_context.global_iteration_responses) == 1
    )
    # Verify inference sections were added to context
    assert len(fake_run_context.context.unordered_fetched_inference_sections) == 2
    assert (
        fake_run_context.context.unordered_fetched_inference_sections[
            0
        ].center_chunk.document_id
        == "doc1"
    )
    assert (
        fake_run_context.context.unordered_fetched_inference_sections[
            1
        ].center_chunk.document_id
        == "doc2"
    )

    # Check iteration instruction
    instruction = fake_run_context.context.iteration_instructions[0]
    assert isinstance(instruction, IterationInstructions)
    assert instruction.iteration_nr == 1
    assert instruction.purpose == "Searching internally for information"
    # Updated to match the list format in reasoning
    assert (
        "I am now using Internal Search to gather information on"
        in instruction.reasoning
    )

    # Check iteration answer
    answer = fake_run_context.context.aggregated_context.global_iteration_responses[0]
    assert isinstance(answer, IterationAnswer)
    assert answer.tool == SearchTool.__name__
    assert answer.tool_id == 1
    assert answer.iteration_nr == 1
    assert answer.question == query
    assert (
        answer.reasoning
        == f"I am now using Internal Search to gather information on {query}"
    )
    assert answer.answer == ""
    assert len(answer.cited_documents) == 2

    # Verify emitter events were captured
    emitter = fake_run_context.context.run_dependencies.emitter
    assert len(emitter.packet_history) == 4

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, SearchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[3].obj, SectionEnd)

    # Check the first SearchToolDelta (query) - now expects a list
    first_delta = emitter.packet_history[1].obj
    assert first_delta.queries == queries
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

    # Verify the pipeline was called with correct parameters
    assert test_pipeline.run_called
    assert test_pipeline.run_kwargs["query"] == query
    assert test_pipeline.run_kwargs["override_kwargs"].force_no_rerank is True
    assert test_pipeline.run_kwargs["override_kwargs"].skip_query_analysis is True
    assert test_pipeline.run_kwargs["override_kwargs"].original_query == query


def test_internal_search_core_with_multiple_queries(
    fake_run_context: RunContextWrapper[ChatTurnContext],
    fake_session_context_manager: FakeSessionContextManager,
) -> None:
    """Test that _internal_search_core can handle multiple queries and execute them in parallel"""
    # Arrange
    queries = ["first query", "second query", "third query"]

    # Create test sections for the search results
    test_sections = [
        create_test_inference_section(
            document_id=f"doc{i}",
            content=f"Content for doc {i}",
            link=f"https://example.com/doc{i}",
        )
        for i in range(1, 4)
    ]

    # Use the existing FakeSearchPipeline with results
    test_pipeline = create_fake_search_pipeline_with_results(sections=test_sections)

    # Track calls to the pipeline
    original_run = test_pipeline.run
    call_count: list[int] = []
    call_queries: list[Any] = []

    def tracked_run(**kwargs: Any) -> list:
        call_count.append(1)
        call_queries.append(kwargs.get("query"))
        return original_run(**kwargs)

    test_pipeline.run = tracked_run  # type: ignore[method-assign]

    # Act
    # Pass all queries to test parallel execution
    result = run_internal_search_core_with_dependencies(
        fake_run_context, queries, test_pipeline, fake_session_context_manager
    )

    # Assert
    assert isinstance(result, list)
    # Should have results from all queries
    assert len(result) > 0
    # Verify result contains LlmDoc objects
    assert all(isinstance(doc, LlmDoc) for doc in result)

    # Verify all queries were executed
    assert len(call_queries) == len(queries)
    assert set(call_queries) == set(
        queries
    ), f"Expected queries {queries}, got {call_queries}"

    # Verify emitter events were captured with all queries
    emitter = fake_run_context.context.run_dependencies.emitter

    # Find the SearchToolDelta with queries
    query_deltas = [
        packet.obj
        for packet in emitter.packet_history
        if isinstance(packet.obj, SearchToolDelta) and packet.obj.queries != []
    ]
    assert (
        len(query_deltas) > 0
    ), "Should have at least one SearchToolDelta with queries"

    # Check that all queries were emitted
    emitted_queries = query_deltas[0].queries
    assert (
        emitted_queries == queries
    ), f"Expected emitted queries {queries}, got {emitted_queries}"
