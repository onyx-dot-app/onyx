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
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebContentProvider
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebSearchProvider
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebSearchResult
from onyx.chat.turn.models import ChatTurnContext
from onyx.configs.constants import DocumentSource
from onyx.server.query_and_chat.streaming_models import FetchToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.web_search.open_url_tool import OpenUrlTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_result_models import LlmOpenUrlResult
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


class MockWebContentProvider(WebContentProvider):
    """Mock implementation of WebContentProvider for dependency injection"""

    def __init__(
        self,
        content_results: List[WebContent] | None = None,
        should_raise_exception: bool = False,
    ):
        self.content_results = content_results or []
        self.should_raise_exception = should_raise_exception

    def contents(self, urls: Sequence[str]) -> List[WebContent]:
        if self.should_raise_exception:
            raise Exception("Test exception from content provider")
        return self.content_results


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


def test_open_url_tool_run_v2_basic_functionality() -> None:
    """Test basic functionality of OpenUrlTool.run_v2"""
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

    test_provider = MockWebContentProvider(content_results=test_content_results)

    # Create tool instance
    open_url_tool = OpenUrlTool(tool_id=1)

    # Mock the get_default_content_provider to return our test provider
    from unittest.mock import patch

    with patch(
        "onyx.tools.tool_implementations.web_search.open_url_tool.get_default_content_provider"
    ) as mock_get_provider:
        mock_get_provider.return_value = test_provider

        # Act
        result_json = open_url_tool.run_v2(test_run_context, urls=urls)

    from pydantic import TypeAdapter

    adapter = TypeAdapter(list[LlmOpenUrlResult])
    result = adapter.validate_json(result_json)

    # Assert
    assert len(result) == 2
    assert all(isinstance(r, LlmOpenUrlResult) for r in result)

    # Check first result
    assert result[0].content == "This is the full content of the first page"
    assert result[0].document_citation_number == -1
    assert result[0].unique_identifier_to_strip_away == "https://example.com/1"

    # Check second result
    assert result[1].content == "This is the full content of the second page"
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
    assert instruction.purpose == "Fetching content from URLs"
    assert (
        "Web Fetch to gather information on https://example.com/1, https://example.com/2"
        in instruction.reasoning
    )

    # Check iteration answer
    answer = test_run_context.context.global_iteration_responses[0]
    assert isinstance(answer, IterationAnswer)
    assert answer.tool == WebSearchTool.__name__
    assert answer.iteration_nr == 1
    assert (
        answer.question
        == "Fetch content from URLs: https://example.com/1, https://example.com/2"
    )
    assert len(answer.cited_documents) == 2

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


def test_open_url_tool_run_v2_exception_handling() -> None:
    """Test that OpenUrlTool.run_v2 handles exceptions properly"""
    # Arrange
    test_run_context = create_test_run_context()
    urls = ["https://example.com/1", "https://example.com/2"]

    # Create a provider that will raise an exception
    test_provider = MockWebContentProvider(should_raise_exception=True)

    # Create tool instance
    open_url_tool = OpenUrlTool(tool_id=1)

    # Mock the get_default_content_provider to return our test provider
    from unittest.mock import patch

    with patch(
        "onyx.tools.tool_implementations.web_search.open_url_tool.get_default_content_provider"
    ) as mock_get_provider:
        mock_get_provider.return_value = test_provider

        # Act & Assert
        with pytest.raises(Exception, match="Test exception from content provider"):
            open_url_tool.run_v2(test_run_context, urls=urls)

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


def test_open_url_tool_run_v2_cache_deduplication() -> None:
    """Test that WebSearchTool.run_v2 and OpenUrlTool.run_v2 share fetched_documents_cache for the same URL"""
    # Arrange
    test_run_context = create_test_run_context()
    test_url = "https://example.com/1"

    # First, do a web search that returns this URL
    search_results = [
        WebSearchResult(
            title="Test Result",
            link=test_url,
            author="Test Author",
            published_date=datetime(2024, 1, 1, 12, 0, 0),
            snippet="This is a test snippet",
        ),
    ]

    # Then, fetch the full content for the same URL
    content_results = [
        WebContent(
            title="Test Content",
            link=test_url,
            full_content="This is the full content of the page",
            published_date=datetime(2024, 1, 1, 12, 0, 0),
        ),
    ]

    search_provider = MockWebSearchProvider(search_results=search_results)
    content_provider = MockWebContentProvider(content_results=content_results)

    web_search_tool = WebSearchTool(tool_id=1)
    open_url_tool = OpenUrlTool(tool_id=1)

    from unittest.mock import patch
    from pydantic import TypeAdapter

    # Act - first do web_search via run_v2
    with patch(
        "onyx.tools.tool_implementations.web_search.web_search_tool.get_default_provider"
    ) as mock_get_provider:
        mock_get_provider.return_value = search_provider
        search_result_json = web_search_tool.run_v2(
            test_run_context, queries=["test query"]
        )

    adapter_ws = TypeAdapter(list[LlmWebSearchResult])
    search_result = adapter_ws.validate_json(search_result_json)

    # Verify search result
    assert len(search_result) == 1
    assert search_result[0].url == test_url

    # Verify cache was populated by web_search
    assert test_url in test_run_context.context.fetched_documents_cache

    # Now run open_url via run_v2
    with patch(
        "onyx.tools.tool_implementations.web_search.open_url_tool.get_default_content_provider"
    ) as mock_get_content_provider:
        mock_get_content_provider.return_value = content_provider
        open_result_json = open_url_tool.run_v2(test_run_context, urls=[test_url])

    adapter_ou = TypeAdapter(list[LlmOpenUrlResult])
    open_result = adapter_ou.validate_json(open_result_json)

    # Verify open_url result
    assert len(open_result) == 1
    assert open_result[0].content == "This is the full content of the page"

    # Verify cache still has the same entry (not duplicated)
    assert len(test_run_context.context.fetched_documents_cache) == 1
    assert test_url in test_run_context.context.fetched_documents_cache
    cache_entry_after_open = test_run_context.context.fetched_documents_cache[test_url]

    # Verify that the cache entry was updated with the full content
    # (The inference section should be updated, not replaced)
    assert cache_entry_after_open.document_citation_number == -1
