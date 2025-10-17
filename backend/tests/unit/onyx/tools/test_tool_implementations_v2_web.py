from datetime import datetime
from typing import cast
from typing import List
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebContent
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebSearchProvider
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchResult,
)
from onyx.chat.turn.models import ChatTurnContext
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SavedSearchDoc
from onyx.server.query_and_chat.streaming_models import FetchToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_implementations_v2.web import _open_url_core
from onyx.tools.tool_implementations_v2.web import _web_search_core
from onyx.tools.tool_implementations_v2.web import OpenUrlResponse
from onyx.tools.tool_implementations_v2.web import WebSearchResponse


class MockTool:
    """Mock Tool object for testing"""

    def __init__(self, tool_id: int = 1, name: str = WebSearchTool.__name__):
        self.id = tool_id
        self.name = name


class MockWebSearchProvider(WebSearchProvider):
    """Mock implementation of WebSearchProvider for dependency injection"""

    def __init__(
        self,
        search_results: List[WebSearchResult] | None = None,
        content_results: List[WebContent] | None = None,
        should_raise_exception: bool = False,
    ):
        self.search_results = search_results or []
        self.content_results = content_results or []
        self.should_raise_exception = should_raise_exception

    def search(self, query: str) -> List[WebSearchResult]:
        if self.should_raise_exception:
            raise Exception("Test exception from search provider")
        return self.search_results

    def contents(self, urls: List[str]) -> List[WebContent]:
        if self.should_raise_exception:
            raise Exception("Test exception from search provider")
        return self.content_results


class MockEmitter:
    """Mock emitter for dependency injection"""

    def __init__(self) -> None:
        self.packet_history: list[Packet] = []

    def emit(self, packet: Packet) -> None:
        self.packet_history.append(packet)


class MockAggregatedContext:
    """Mock aggregated context for dependency injection"""

    def __init__(self) -> None:
        self.global_iteration_responses: list[IterationAnswer] = []
        self.cited_documents: list[InferenceSection] = []


class MockRunDependencies:
    """Mock run dependencies for dependency injection"""

    def __init__(self) -> None:
        self.emitter = MockEmitter()
        # Set up mock database session
        self.db_session = MagicMock()
        # Configure the scalar method to return our mock tool
        mock_tool = MockTool()
        self.db_session.scalar.return_value = mock_tool


def create_test_run_context(
    current_run_step: int = 0,
    iteration_instructions: List[IterationInstructions] | None = None,
    global_iteration_responses: List[IterationAnswer] | None = None,
) -> RunContextWrapper[ChatTurnContext]:
    """Create a real RunContextWrapper with test dependencies"""

    # Create test dependencies
    emitter = MockEmitter()
    aggregated_context = MockAggregatedContext()
    if global_iteration_responses:
        aggregated_context.global_iteration_responses = global_iteration_responses

    run_dependencies = MockRunDependencies()
    run_dependencies.emitter = emitter

    # Create the actual context object
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.THOUGHTFUL,
        current_run_step=current_run_step,
        iteration_instructions=iteration_instructions or [],
        aggregated_context=aggregated_context,  # type: ignore[arg-type]
        run_dependencies=run_dependencies,  # type: ignore[arg-type]
    )

    # Create the run context wrapper
    run_context = RunContextWrapper(context=context)

    return run_context


def test_web_search_core_basic_functionality() -> None:
    """Test basic functionality of _web_search_core function with a single query"""
    # Arrange
    test_run_context = create_test_run_context()
    queries = ["test search query"]

    # Create test search results
    test_search_results = [
        WebSearchResult(
            title="Test Result 1",
            link="https://example.com/1",
            author="Test Author",
            published_date=datetime(2024, 1, 1, 12, 0, 0),
            snippet="This is a test snippet 1",
        ),
        WebSearchResult(
            title="Test Result 2",
            link="https://example.com/2",
            author=None,
            published_date=None,
            snippet="This is a test snippet 2",
        ),
    ]

    test_provider = MockWebSearchProvider(search_results=test_search_results)

    # Act
    result = _web_search_core(test_run_context, queries, test_provider)

    # Assert
    assert isinstance(result, WebSearchResponse)
    assert len(result.results) == 2

    # Check first result
    assert result.results[0].tag == "1"
    assert result.results[0].title == "Test Result 1"
    assert result.results[0].link == "https://example.com/1"
    assert result.results[0].author == "Test Author"
    assert result.results[0].published_date == "2024-01-01T12:00:00"
    assert result.results[0].snippet == "This is a test snippet 1"

    # Check second result
    assert result.results[1].tag == "2"
    assert result.results[1].title == "Test Result 2"
    assert result.results[1].link == "https://example.com/2"
    assert result.results[1].author is None
    assert result.results[1].published_date is None
    assert result.results[1].snippet == "This is a test snippet 2"

    # Verify context was updated
    assert test_run_context.context.current_run_step == 2
    assert len(test_run_context.context.iteration_instructions) == 1
    assert (
        len(test_run_context.context.aggregated_context.global_iteration_responses) == 1
    )

    # Check iteration instruction
    instruction = test_run_context.context.iteration_instructions[0]
    assert isinstance(instruction, IterationInstructions)
    assert instruction.iteration_nr == 1
    assert instruction.purpose == "Searching the web for information"
    assert (
        "Web Search to gather information on test search query" in instruction.reasoning
    )

    # Check iteration answer
    answer = test_run_context.context.aggregated_context.global_iteration_responses[0]
    assert isinstance(answer, IterationAnswer)
    assert answer.tool == WebSearchTool.__name__
    assert answer.iteration_nr == 1
    assert answer.question == queries[0]
    assert len(answer.cited_documents) == 2

    # Verify cited_documents were added to aggregated_context
    assert len(test_run_context.context.aggregated_context.cited_documents) == 2
    # Web documents have "INTERNET_SEARCH_DOC_" prefix added to the URL
    assert (
        test_run_context.context.aggregated_context.cited_documents[
            0
        ].center_chunk.document_id
        == "INTERNET_SEARCH_DOC_https://example.com/1"
    )
    assert (
        test_run_context.context.aggregated_context.cited_documents[
            1
        ].center_chunk.document_id
        == "INTERNET_SEARCH_DOC_https://example.com/2"
    )

    # Verify emitter events were captured
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 3

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, SearchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SectionEnd)


def test_web_fetch_core_basic_functionality() -> None:
    """Test basic functionality of _web_fetch_core function"""
    # Arrange
    test_run_context = create_test_run_context()
    urls = ["https://example.com/1", "https://example.com/2"]

    # Create test content results
    test_content_results = [
        WebContent(
            title="Test Content 1",
            link="https://example.com/1",
            full_content="This is the full content of the first page",
            published_date=datetime(2024, 1, 1, 12, 0, 0),
        ),
        WebContent(
            title="Test Content 2",
            link="https://example.com/2",
            full_content="This is the full content of the second page",
            published_date=None,
        ),
    ]

    test_provider = MockWebSearchProvider(content_results=test_content_results)

    # Act
    result = _open_url_core(test_run_context, urls, test_provider)

    # Assert
    assert isinstance(result, OpenUrlResponse)
    assert len(result.results) == 2

    # Check first result
    assert result.results[0].tag == "1"
    assert result.results[0].title == "Test Content 1"
    assert result.results[0].link == "https://example.com/1"
    assert (
        result.results[0].truncated_content
        == "This is the full content of the first page"
    )
    assert result.results[0].published_date == "2024-01-01T12:00:00"

    # Check second result
    assert result.results[1].tag == "2"
    assert result.results[1].title == "Test Content 2"
    assert result.results[1].link == "https://example.com/2"
    assert (
        result.results[1].truncated_content
        == "This is the full content of the second page"
    )
    assert result.results[1].published_date is None

    # Verify context was updated
    assert test_run_context.context.current_run_step == 2
    assert len(test_run_context.context.iteration_instructions) == 1
    assert (
        len(test_run_context.context.aggregated_context.global_iteration_responses) == 1
    )

    # Check iteration instruction
    instruction = test_run_context.context.iteration_instructions[0]
    assert isinstance(instruction, IterationInstructions)
    assert instruction.iteration_nr == 1
    assert instruction.purpose == "Fetching content from URLs"
    assert (
        "Web Fetch to gather information on https://example.com/1, https://example.com/2"
        in instruction.reasoning
    )

    # Check iteration answer
    answer = test_run_context.context.aggregated_context.global_iteration_responses[0]
    assert isinstance(answer, IterationAnswer)
    assert answer.tool == WebSearchTool.__name__
    assert answer.iteration_nr == 1
    assert (
        answer.question
        == "Fetch content from URLs: https://example.com/1, https://example.com/2"
    )
    assert len(answer.cited_documents) == 2

    # Verify cited_documents were added to the answer but NOT to aggregated_context.cited_documents
    # (web fetch adds documents to the answer but not to the global cited_documents list)
    assert len(test_run_context.context.aggregated_context.cited_documents) == 0

    # Verify emitter events were captured
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 2

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, FetchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SectionEnd)

    # Verify the FetchToolStart event contains the correct SavedSearchDoc objects
    fetch_start_event = emitter.packet_history[0].obj
    assert len(fetch_start_event.documents) == 2
    assert fetch_start_event.documents[0].link == "https://example.com/1"
    assert fetch_start_event.documents[1].link == "https://example.com/2"
    assert fetch_start_event.documents[0].source_type == DocumentSource.WEB


def test_web_search_core_exception_handling() -> None:
    """Test that _web_search_core handles exceptions properly - should still emit section end and update current_run_step"""
    # Arrange
    test_run_context = create_test_run_context()
    queries = ["test search query"]

    # Create a provider that will raise an exception
    test_provider = MockWebSearchProvider(should_raise_exception=True)

    # Act & Assert
    with pytest.raises(Exception, match="Test exception from search provider"):
        _web_search_core(test_run_context, queries, test_provider)

    # Verify that even though an exception was raised, we still emitted the initial events
    # and the SectionEnd packet was emitted by the decorator
    emitter = test_run_context.context.run_dependencies.emitter  # type: ignore[attr-defined]
    assert (
        len(emitter.packet_history) == 3
    )  # SearchToolStart, SearchToolDelta, and SectionEnd

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, SearchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SectionEnd)

    # Verify that the decorator properly handled the exception and updated current_run_step
    assert (
        test_run_context.context.current_run_step == 2
    )  # Should be 2 after proper handling


def test_web_search_core_multiple_queries() -> None:
    """Test _web_search_core function with multiple queries searched in parallel"""
    # Arrange
    test_run_context = create_test_run_context()
    queries = ["first query", "second query"]

    # Create a mock provider that returns different results based on the query
    class MultiQueryMockProvider(WebSearchProvider):
        def search(self, query: str) -> List[WebSearchResult]:
            if query == "first query":
                return [
                    WebSearchResult(
                        title="First Result 1",
                        link="https://example.com/first1",
                        author="Author 1",
                        published_date=datetime(2024, 1, 1, 12, 0, 0),
                        snippet="Snippet for first query result 1",
                    ),
                    WebSearchResult(
                        title="First Result 2",
                        link="https://example.com/first2",
                        author=None,
                        published_date=None,
                        snippet="Snippet for first query result 2",
                    ),
                ]
            elif query == "second query":
                return [
                    WebSearchResult(
                        title="Second Result 1",
                        link="https://example.com/second1",
                        author="Author 2",
                        published_date=datetime(2024, 2, 1, 12, 0, 0),
                        snippet="Snippet for second query result 1",
                    ),
                ]
            return []

        def contents(self, urls: List[str]) -> List[WebContent]:
            return []

    test_provider = MultiQueryMockProvider()

    # Act
    result = _web_search_core(test_run_context, queries, test_provider)

    # Assert
    assert isinstance(result, WebSearchResponse)
    # Should have 3 total results (2 from first query + 1 from second query)
    assert len(result.results) == 3

    # Verify all results are present (order may vary due to parallel execution)
    titles = {r.title for r in result.results}
    assert "First Result 1" in titles
    assert "First Result 2" in titles
    assert "Second Result 1" in titles

    # Verify context was updated
    assert test_run_context.context.current_run_step == 2
    assert len(test_run_context.context.iteration_instructions) == 1
    assert (
        len(test_run_context.context.aggregated_context.global_iteration_responses) == 1
    )

    # Check iteration instruction contains both queries
    instruction = test_run_context.context.iteration_instructions[0]
    assert isinstance(instruction, IterationInstructions)
    assert instruction.iteration_nr == 1
    assert instruction.purpose == "Searching the web for information"
    assert "first query" in instruction.reasoning
    assert "second query" in instruction.reasoning

    # Check iteration answer
    answer = test_run_context.context.aggregated_context.global_iteration_responses[0]
    assert isinstance(answer, IterationAnswer)
    assert answer.tool == WebSearchTool.__name__
    assert answer.iteration_nr == 1
    assert "first query" in answer.question
    assert "second query" in answer.question
    assert len(answer.cited_documents) == 3

    # Verify cited_documents were added to aggregated_context
    assert len(test_run_context.context.aggregated_context.cited_documents) == 3
    # Verify at least one of the cited documents has the correct format
    document_ids = [
        doc.center_chunk.document_id
        for doc in test_run_context.context.aggregated_context.cited_documents
    ]
    assert any(
        "INTERNET_SEARCH_DOC_https://example.com/first" in doc_id
        for doc_id in document_ids
    )
    assert any(
        "INTERNET_SEARCH_DOC_https://example.com/second" in doc_id
        for doc_id in document_ids
    )

    # Verify emitter events were captured
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 3

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, SearchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SectionEnd)

    # Check that SearchToolDelta contains both queries
    search_delta = emitter.packet_history[1].obj
    assert search_delta.queries is not None
    assert len(search_delta.queries) == 2
    assert "first query" in search_delta.queries
    assert "second query" in search_delta.queries


def test_web_fetch_core_exception_handling() -> None:
    """Test that _web_fetch_core handles exceptions properly - should still emit section end and update current_run_step"""
    # Arrange
    test_run_context = create_test_run_context()
    urls = ["https://example.com/1", "https://example.com/2"]

    # Create a provider that will raise an exception
    test_provider = MockWebSearchProvider(should_raise_exception=True)

    # Act & Assert
    with pytest.raises(Exception, match="Test exception from search provider"):
        _open_url_core(test_run_context, urls, test_provider)

    # Verify that even though an exception was raised, we still emitted the initial events
    # and the SectionEnd packet was emitted by the decorator
    emitter = test_run_context.context.run_dependencies.emitter  # type: ignore[attr-defined]
    assert len(emitter.packet_history) == 2  # FetchToolStart and SectionEnd

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, FetchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SectionEnd)

    # Verify that the decorator properly handled the exception and updated current_run_step
    assert (
        test_run_context.context.current_run_step == 2
    )  # Should be 2 after proper handling


def test_saved_search_doc_from_url() -> None:
    """Test that SavedSearchDoc.from_url creates a properly formatted document for internet search"""
    # Arrange
    test_url = "https://example.com/test-page"

    # Act
    doc = SavedSearchDoc.from_url(test_url)

    # Assert
    assert doc.document_id == "INTERNET_SEARCH_DOC_" + test_url
    assert doc.link == test_url
    assert doc.semantic_identifier == test_url
    assert doc.source_type == DocumentSource.WEB
    assert doc.is_internet is True
    assert doc.db_doc_id == 0
    assert doc.chunk_ind == 0
    assert doc.boost == 1
    assert doc.hidden is False
    assert doc.score == 0.0
