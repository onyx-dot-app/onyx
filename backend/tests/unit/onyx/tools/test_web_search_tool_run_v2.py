from collections.abc import Sequence
from datetime import datetime
from typing import cast
from typing import List
from uuid import uuid4

import pytest
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebContent
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebSearchProvider
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebSearchResult
from onyx.chat.turn.models import ChatTurnContext
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SavedSearchDoc
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_result_models import LlmWebSearchResult


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
        should_raise_exception: bool = False,
    ):
        self.search_results = search_results or []
        self.should_raise_exception = should_raise_exception

    def search(self, query: str) -> List[WebSearchResult]:
        if self.should_raise_exception:
            raise Exception("Test exception from search provider")
        return self.search_results

    def contents(self, urls: Sequence[str]) -> List[WebContent]:
        return []


class MockEmitter:
    """Mock emitter for dependency injection"""

    def __init__(self) -> None:
        self.packet_history: list[Packet] = []

    def emit(self, packet: Packet) -> None:
        self.packet_history.append(packet)


class MockRunDependencies:
    """Mock run dependencies for dependency injection"""

    def __init__(self) -> None:
        self.emitter = MockEmitter()
        # Set up mock database session
        from unittest.mock import MagicMock

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
    run_dependencies = MockRunDependencies()
    run_dependencies.emitter = emitter

    # Create the actual context object
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        current_run_step=current_run_step,
        iteration_instructions=iteration_instructions or [],
        global_iteration_responses=global_iteration_responses or [],
        run_dependencies=run_dependencies,  # type: ignore[arg-type]
    )

    # Create the run context wrapper
    run_context = RunContextWrapper(context=context)

    return run_context


def test_web_search_tool_run_v2_basic_functionality() -> None:
    """Test basic functionality of WebSearchTool.run_v2 with a single query"""
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

    # Create tool instance
    web_search_tool = WebSearchTool(tool_id=1)

    # Mock the get_default_provider to return our test provider
    from unittest.mock import patch

    with patch(
        "onyx.tools.tool_implementations.web_search.web_search_tool.get_default_provider"
    ) as mock_get_provider:
        mock_get_provider.return_value = test_provider

        # Act
        result_json = web_search_tool.run_v2(test_run_context, queries=queries)

    # Parse the JSON result
    from pydantic import TypeAdapter

    adapter = TypeAdapter(list[LlmWebSearchResult])
    result = adapter.validate_json(result_json)

    # Assert
    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(r, LlmWebSearchResult) for r in result)

    # Check first result
    assert result[0].title == "Test Result 1"
    assert result[0].url == "https://example.com/1"
    assert result[0].snippet == "This is a test snippet 1"
    assert result[0].document_citation_number == -1
    assert result[0].unique_identifier_to_strip_away == "https://example.com/1"

    # Check second result
    assert result[1].title == "Test Result 2"
    assert result[1].url == "https://example.com/2"
    assert result[1].snippet == "This is a test snippet 2"
    assert result[1].document_citation_number == -1
    assert result[1].unique_identifier_to_strip_away == "https://example.com/2"

    # Check that fetched_documents_cache was populated
    assert len(test_run_context.context.fetched_documents_cache) == 2
    assert "https://example.com/1" in test_run_context.context.fetched_documents_cache
    assert "https://example.com/2" in test_run_context.context.fetched_documents_cache

    # Verify cache entries have correct structure
    cache_entry_1 = test_run_context.context.fetched_documents_cache[
        "https://example.com/1"
    ]
    assert cache_entry_1.document_citation_number == -1
    assert cache_entry_1.inference_section is not None

    # Verify context was updated
    assert test_run_context.context.current_run_step == 2
    assert len(test_run_context.context.iteration_instructions) == 1
    assert len(test_run_context.context.global_iteration_responses) == 1

    # Check iteration instruction
    instruction = test_run_context.context.iteration_instructions[0]
    assert isinstance(instruction, IterationInstructions)
    assert instruction.iteration_nr == 1
    assert instruction.purpose == "Searching the web for information"
    assert (
        "Web Search to gather information on test search query" in instruction.reasoning
    )

    # Check iteration answer
    answer = test_run_context.context.global_iteration_responses[0]
    assert isinstance(answer, IterationAnswer)
    assert answer.tool == WebSearchTool.__name__
    assert answer.iteration_nr == 1
    assert answer.question == queries[0]

    # Verify emitter events were captured
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 4

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, SearchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[3].obj, SectionEnd)

    # Verify first SearchToolDelta has queries but empty documents
    first_search_delta = cast(SearchToolDelta, emitter.packet_history[1].obj)
    assert first_search_delta.queries == queries
    assert first_search_delta.documents == []

    # Verify second SearchToolDelta contains SavedSearchDoc objects for favicon display
    search_tool_delta = cast(SearchToolDelta, emitter.packet_history[2].obj)
    assert len(search_tool_delta.documents) == 2

    # Verify documents have correct properties for frontend favicon display
    doc1 = search_tool_delta.documents[0]
    assert isinstance(doc1, SavedSearchDoc)
    assert doc1.link == "https://example.com/1"
    assert (
        doc1.semantic_identifier == "https://example.com/1"
    )  # semantic_identifier is the link for web results
    assert doc1.blurb == "Test Result 1"  # title is stored in blurb
    assert doc1.source_type == DocumentSource.WEB
    assert doc1.is_internet is True


def test_web_search_tool_run_v2_exception_handling() -> None:
    """Test that WebSearchTool.run_v2 handles exceptions properly"""
    # Arrange
    test_run_context = create_test_run_context()
    queries = ["test search query"]

    # Create a provider that will raise an exception
    test_provider = MockWebSearchProvider(should_raise_exception=True)

    # Create tool instance
    web_search_tool = WebSearchTool(tool_id=1)

    # Mock the get_default_provider to return our test provider
    from unittest.mock import patch

    with patch(
        "onyx.tools.tool_implementations.web_search.web_search_tool.get_default_provider"
    ) as mock_get_provider:
        mock_get_provider.return_value = test_provider

        # Act & Assert
        with pytest.raises(Exception, match="Test exception from search provider"):
            web_search_tool.run_v2(test_run_context, queries=queries)

    # Verify that even though an exception was raised, we still emitted the initial events
    # and the SectionEnd packet was emitted by the decorator
    emitter = test_run_context.context.run_dependencies.emitter  # type: ignore[attr-defined]
    assert (
        len(emitter.packet_history) == 3
    )  # SearchToolStart, first SearchToolDelta, and SectionEnd

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, SearchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SectionEnd)

    # Verify that the decorator properly handled the exception and updated current_run_step
    assert (
        test_run_context.context.current_run_step == 2
    )  # Should be 2 after proper handling


def test_web_search_tool_run_v2_multiple_queries() -> None:
    """Test WebSearchTool.run_v2 with multiple queries searched in parallel"""
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

        def contents(self, urls: Sequence[str]) -> List[WebContent]:
            return []

    test_provider = MultiQueryMockProvider()

    # Create tool instance
    web_search_tool = WebSearchTool(tool_id=1)

    # Mock the get_default_provider to return our test provider
    from unittest.mock import patch

    with patch(
        "onyx.tools.tool_implementations.web_search.web_search_tool.get_default_provider"
    ) as mock_get_provider:
        mock_get_provider.return_value = test_provider

        # Act
        result_json = web_search_tool.run_v2(test_run_context, queries=queries)

    # Parse the JSON result
    from pydantic import TypeAdapter

    adapter = TypeAdapter(list[LlmWebSearchResult])
    result = adapter.validate_json(result_json)

    # Assert
    assert isinstance(result, list)
    # Should have 3 total results (2 from first query + 1 from second query)
    assert len(result) == 3
    assert all(isinstance(r, LlmWebSearchResult) for r in result)

    # Verify all results are present (order may vary due to parallel execution)
    titles = {r.title for r in result}
    assert "First Result 1" in titles
    assert "First Result 2" in titles
    assert "Second Result 1" in titles

    # Check that fetched_documents_cache was populated with all URLs
    assert len(test_run_context.context.fetched_documents_cache) == 3

    # Verify context was updated
    assert test_run_context.context.current_run_step == 2
    assert len(test_run_context.context.iteration_instructions) == 1
    assert len(test_run_context.context.global_iteration_responses) == 1

    # Check iteration instruction contains both queries
    instruction = test_run_context.context.iteration_instructions[0]
    assert isinstance(instruction, IterationInstructions)
    assert instruction.iteration_nr == 1
    assert instruction.purpose == "Searching the web for information"
    assert "first query" in instruction.reasoning
    assert "second query" in instruction.reasoning

    # Check iteration answer
    answer = test_run_context.context.global_iteration_responses[0]
    assert isinstance(answer, IterationAnswer)
    assert answer.tool == WebSearchTool.__name__
    assert answer.iteration_nr == 1
    assert "first query" in answer.question
    assert "second query" in answer.question

    # Verify emitter events were captured
    emitter = cast(MockEmitter, test_run_context.context.run_dependencies.emitter)
    assert len(emitter.packet_history) == 4

    # Check the types of emitted events
    assert isinstance(emitter.packet_history[0].obj, SearchToolStart)
    assert isinstance(emitter.packet_history[1].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[2].obj, SearchToolDelta)
    assert isinstance(emitter.packet_history[3].obj, SectionEnd)

    # Check that first SearchToolDelta contains both queries (with empty documents)
    first_search_delta = cast(SearchToolDelta, emitter.packet_history[1].obj)
    assert first_search_delta.queries is not None
    assert len(first_search_delta.queries) == 2
    assert "first query" in first_search_delta.queries
    assert "second query" in first_search_delta.queries
    assert first_search_delta.documents == []

    # Check that second SearchToolDelta contains documents
    second_search_delta = cast(SearchToolDelta, emitter.packet_history[2].obj)
    assert (
        len(second_search_delta.documents) == 3
    )  # 2 from first query + 1 from second query
