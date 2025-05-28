from datetime import datetime
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID

import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter
from sqlalchemy.orm import Session

from onyx.agents.agent_search.basic.states import BasicState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.models import GraphInputs
from onyx.agents.agent_search.models import GraphPersistence
from onyx.agents.agent_search.models import GraphSearchConfig
from onyx.agents.agent_search.models import GraphTooling
from onyx.agents.agent_search.orchestration.nodes.use_tool_response import (
    basic_use_tool_response,
)
from onyx.agents.agent_search.orchestration.states import ToolCallOutput
from onyx.agents.agent_search.orchestration.states import ToolChoice
from onyx.chat.models import DocumentSource
from onyx.chat.models import LlmDoc
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.context.search.enums import QueryFlow
from onyx.context.search.enums import SearchType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchRequest
from onyx.llm.interfaces import LLM
from onyx.tools.force import ForceUseTool
from onyx.tools.message import ToolCallSummary
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.search.search_utils import section_to_llm_doc
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)


def create_test_inference_chunk(
    document_id: str,
    chunk_id: int,
    content: str,
    score: float | None,
    semantic_identifier: str,
    title: str,
) -> InferenceChunk:
    """Helper function to create test InferenceChunks with consistent defaults."""
    return InferenceChunk(
        chunk_id=chunk_id,
        blurb=f"Chunk {chunk_id} from {document_id}",
        content=content,
        source_links={0: f"{document_id}_link"},
        section_continuation=False,
        document_id=document_id,
        source_type=DocumentSource.FILE,
        image_file_name=None,
        title=title,
        semantic_identifier=semantic_identifier,
        boost=1,
        recency_bias=1.0,
        score=score,
        hidden=False,
        primary_owners=None,
        secondary_owners=None,
        large_chunk_reference_ids=[],
        metadata={},
        doc_summary=f"Summary of {document_id}",
        chunk_context=f"Context for chunk{chunk_id}",
        match_highlights=[f"<hi>chunk{chunk_id}</hi>"],
        updated_at=datetime.now(),
    )


@pytest.fixture
def mock_state() -> BasicState:
    mock_tool = MagicMock(spec=SearchTool)
    mock_tool.build_next_prompt = MagicMock(
        return_value=MagicMock(spec=AnswerPromptBuilder)
    )
    mock_tool.build_next_prompt.return_value.build = MagicMock(
        return_value="test prompt"
    )

    mock_tool_choice = MagicMock(spec=ToolChoice)
    mock_tool_choice.tool = mock_tool
    mock_tool_choice.tool_args = {}
    mock_tool_choice.id = "test_id"
    mock_tool_choice.search_tool_override_kwargs = None

    mock_tool_call_output = MagicMock(spec=ToolCallOutput)
    mock_tool_call_output.tool_call_summary = ToolCallSummary(
        tool_call_request=AIMessageChunk(content=""),
        tool_call_result=ToolMessage(content="", tool_call_id="test_id"),
    )
    mock_tool_call_output.tool_call_responses = []
    mock_tool_call_output.tool_call_kickoff = MagicMock()
    mock_tool_call_output.tool_call_final_result = MagicMock()

    state = BasicState(
        unused=True,  # From BasicInput
        should_stream_answer=True,  # From ToolChoiceInput
        prompt_snapshot=None,  # From ToolChoiceInput
        tools=[],  # From ToolChoiceInput
        tool_call_output=mock_tool_call_output,  # From ToolCallUpdate
        tool_choice=mock_tool_choice,  # From ToolChoiceUpdate
    )
    return state


@pytest.fixture
def mock_config() -> RunnableConfig:
    # Create mock objects for each component
    mock_primary_llm = MagicMock(spec=LLM)
    mock_fast_llm = MagicMock(spec=LLM)
    mock_search_tool = MagicMock(spec=SearchTool)
    mock_force_use_tool = MagicMock(spec=ForceUseTool)
    mock_prompt_builder = MagicMock(spec=AnswerPromptBuilder)
    mock_search_request = MagicMock(spec=SearchRequest)
    mock_db_session = MagicMock(spec=Session)

    # Create the GraphConfig components
    graph_inputs = GraphInputs(
        search_request=mock_search_request,
        prompt_builder=mock_prompt_builder,
        files=None,
        structured_response_format=None,
    )

    graph_tooling = GraphTooling(
        primary_llm=mock_primary_llm,
        fast_llm=mock_fast_llm,
        search_tool=mock_search_tool,
        tools=[mock_search_tool],
        force_use_tool=mock_force_use_tool,
        using_tool_calling_llm=True,
    )

    graph_persistence = GraphPersistence(
        chat_session_id=UUID("00000000-0000-0000-0000-000000000000"),
        message_id=1,
        db_session=mock_db_session,
    )

    graph_search_config = GraphSearchConfig(
        use_agentic_search=False,
        perform_initial_search_decomposition=True,
        allow_refinement=True,
        skip_gen_ai_answer_generation=False,
        allow_agent_reranking=False,
    )

    # Create the final GraphConfig
    graph_config = GraphConfig(
        inputs=graph_inputs,
        tooling=graph_tooling,
        persistence=graph_persistence,
        behavior=graph_search_config,
    )

    return RunnableConfig(metadata={"config": graph_config})


@pytest.fixture
def mock_writer() -> MagicMock:
    return MagicMock(spec=StreamWriter)


def test_basic_use_tool_response_with_none_tool_choice(
    mock_state: BasicState, mock_config: RunnableConfig, mock_writer: MagicMock
) -> None:
    mock_state.tool_choice = None
    with pytest.raises(ValueError, match="Tool choice is None"):
        basic_use_tool_response(mock_state, mock_config, mock_writer)


def test_basic_use_tool_response_with_none_tool_call_output(
    mock_state: BasicState, mock_config: RunnableConfig, mock_writer: MagicMock
) -> None:
    mock_state.tool_call_output = None
    with pytest.raises(ValueError, match="Tool call output is None"):
        basic_use_tool_response(mock_state, mock_config, mock_writer)


@patch(
    "onyx.agents.agent_search.orchestration.nodes.use_tool_response.process_llm_stream"
)
def test_basic_use_tool_response_with_search_results(
    mock_process_llm_stream: MagicMock,
    mock_state: BasicState,
    mock_config: RunnableConfig,
    mock_writer: MagicMock,
) -> None:
    # Create chunks for first document
    doc1_chunk1 = create_test_inference_chunk(
        document_id="doc1",
        chunk_id=1,
        content="This is the first chunk from document 1",
        score=0.9,
        semantic_identifier="doc1_identifier",
        title="Document 1",
    )

    doc1_chunk2 = create_test_inference_chunk(
        document_id="doc1",
        chunk_id=2,
        content="This is the second chunk from document 1",
        score=0.8,
        semantic_identifier="doc1_identifier",
        title="Document 1",
    )

    doc1_chunk4 = create_test_inference_chunk(
        document_id="doc1",
        chunk_id=4,
        content="This is the fourth chunk from document 1",
        score=0.8,
        semantic_identifier="doc1_identifier",
        title="Document 1",
    )

    # Create chunks for second document
    doc2_chunk1 = create_test_inference_chunk(
        document_id="doc2",
        chunk_id=1,
        content="This is the first chunk from document 2",
        score=0.95,
        semantic_identifier="doc2_identifier",
        title="Document 2",
    )

    doc2_chunk2 = create_test_inference_chunk(
        document_id="doc2",
        chunk_id=2,
        content="This is the second chunk from document 2",
        score=0.85,
        semantic_identifier="doc2_identifier",
        title="Document 2",
    )

    # Create sections from the chunks
    doc1_section = InferenceSection(
        center_chunk=doc1_chunk1,
        chunks=[doc1_chunk1, doc1_chunk2],
        combined_content="This is the first chunk from document 1\nThis is the second chunk from document 1",
    )

    doc2_section = InferenceSection(
        center_chunk=doc2_chunk1,
        chunks=[doc2_chunk1, doc2_chunk2],
        combined_content="This is the first chunk from document 2\nThis is the second chunk from document 2",
    )

    doc1_section2 = InferenceSection(
        center_chunk=doc1_chunk4,
        chunks=[doc1_chunk4],
        combined_content="This is the fourth chunk from document 1",
    )

    # Create final documents
    mock_final_docs = [
        LlmDoc(
            document_id="doc1",
            content="final doc1 content",
            blurb="test blurb1",
            semantic_identifier="doc1_identifier",
            source_type=DocumentSource.FILE,
            metadata={},
            updated_at=datetime.now(),
            link=None,
            source_links=None,
            match_highlights=None,
        ),
        LlmDoc(
            document_id="doc2",
            content="final doc2 content",
            blurb="test blurb2",
            semantic_identifier="doc2_identifier",
            source_type=DocumentSource.FILE,
            metadata={},
            updated_at=datetime.now(),
            link=None,
            source_links=None,
            match_highlights=None,
        ),
    ]

    # Create search response summary with both sections
    mock_search_response_summary = SearchResponseSummary(
        top_sections=[doc1_section, doc2_section, doc1_section2],
        predicted_search=SearchType.SEMANTIC,
        final_filters=IndexFilters(access_control_list=None),
        recency_bias_multiplier=1.0,
        predicted_flow=QueryFlow.QUESTION_ANSWER,
    )

    assert mock_state.tool_call_output is not None
    mock_state.tool_call_output.tool_call_responses = [
        MagicMock(id=SEARCH_RESPONSE_SUMMARY_ID, response=mock_search_response_summary),
        MagicMock(id=FINAL_CONTEXT_DOCUMENTS_ID, response=mock_final_docs),
    ]

    # Mock the LLM stream
    mock_config["metadata"]["config"].tooling.primary_llm.stream.return_value = iter([])

    # Mock process_llm_stream to return a message chunk
    mock_process_llm_stream.return_value = AIMessageChunk(content="test response")

    # Call the function
    result = basic_use_tool_response(mock_state, mock_config, mock_writer)

    assert mock_state.tool_choice is not None
    assert mock_state.tool_choice.tool is not None
    # Verify the tool's build_next_prompt was called correctly
    mock_build_next = cast(MagicMock, mock_state.tool_choice.tool.build_next_prompt)

    mock_build_next.assert_called_once_with(
        prompt_builder=mock_config["metadata"]["config"].inputs.prompt_builder,
        tool_call_summary=mock_state.tool_call_output.tool_call_summary,
        tool_responses=mock_state.tool_call_output.tool_call_responses,
        using_tool_calling_llm=True,
    )

    # Verify LLM stream was called correctly
    mock_config["metadata"][
        "config"
    ].tooling.primary_llm.stream.assert_called_once_with(
        prompt="test prompt",
        structured_response_format=None,
    )

    # Verify process_llm_stream was called correctly
    mock_process_llm_stream.assert_called_once()
    call_args = mock_process_llm_stream.call_args[1]

    assert call_args["final_search_results"] == mock_final_docs
    assert call_args["displayed_search_results"] == [
        section_to_llm_doc(doc1_section),
        section_to_llm_doc(doc2_section),
    ]

    # Verify the result
    assert result["tool_call_chunk"] == mock_process_llm_stream.return_value


def test_basic_use_tool_response_with_skip_gen_ai(
    mock_state: BasicState, mock_config: RunnableConfig, mock_writer: MagicMock
) -> None:
    # Set skip_gen_ai_answer_generation to True
    mock_config["metadata"]["config"].behavior.skip_gen_ai_answer_generation = True

    result = basic_use_tool_response(mock_state, mock_config, mock_writer)

    # Verify that LLM stream was not called
    mock_config["metadata"]["config"].tooling.primary_llm.stream.assert_not_called()

    # Verify the result contains an empty message chunk
    assert result["tool_call_chunk"] == AIMessageChunk(content="")
