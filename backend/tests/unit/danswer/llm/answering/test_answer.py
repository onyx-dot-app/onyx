import json
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolCall
from langchain_core.messages import ToolCallChunk

from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import DanswerQuote
from danswer.chat.models import DanswerQuotes
from danswer.chat.models import LlmDoc
from danswer.chat.models import StreamStopInfo
from danswer.chat.models import StreamStopReason
from danswer.llm.answering.answer import Answer
from danswer.llm.answering.models import AnswerStyleConfig
from danswer.llm.answering.models import PromptConfig
from danswer.llm.answering.models import QuotesConfig
from danswer.llm.interfaces import LLM
from danswer.tools.force import ForceUseTool
from danswer.tools.models import ToolCallFinalResult
from danswer.tools.models import ToolCallKickoff
from danswer.tools.models import ToolResponse
from tests.unit.danswer.llm.answering.conftest import DEFAULT_SEARCH_ARGS
from tests.unit.danswer.llm.answering.conftest import QUERY


@pytest.fixture
def answer_instance(
    mock_llm: LLM, answer_style_config: AnswerStyleConfig, prompt_config: PromptConfig
) -> Answer:
    return Answer(
        question=QUERY,
        answer_style_config=answer_style_config,
        llm=mock_llm,
        prompt_config=prompt_config,
        force_use_tool=ForceUseTool(force_use=False, tool_name="", args=None),
    )


def test_basic_answer(answer_instance: Answer) -> None:
    mock_llm = cast(Mock, answer_instance.llm)
    mock_llm.stream.return_value = [
        AIMessageChunk(content="This is a "),
        AIMessageChunk(content="mock answer."),
    ]

    output = list(answer_instance.processed_streamed_output)
    assert len(output) == 2
    assert isinstance(output[0], DanswerAnswerPiece)
    assert isinstance(output[1], DanswerAnswerPiece)

    full_answer = "".join(
        piece.answer_piece
        for piece in output
        if isinstance(piece, DanswerAnswerPiece) and piece.answer_piece is not None
    )
    assert full_answer == "This is a mock answer."

    assert answer_instance.llm_answer == "This is a mock answer."
    assert answer_instance.citations == []

    assert mock_llm.stream.call_count == 1
    mock_llm.stream.assert_called_once_with(
        prompt=[
            SystemMessage(content="System prompt"),
            HumanMessage(content="Task prompt\n\nQUERY:\nTest question"),
        ],
        tools=None,
        tool_choice=None,
        structured_response_format=None,
    )


@pytest.mark.parametrize(
    "force_use_tool, expected_tool_args",
    [
        (
            ForceUseTool(force_use=False, tool_name="", args=None),
            DEFAULT_SEARCH_ARGS,
        ),
        (
            ForceUseTool(
                force_use=True, tool_name="search", args={"query": "forced search"}
            ),
            {"query": "forced search"},
        ),
    ],
)
def test_answer_with_search_call(
    answer_instance: Answer,
    mock_search_results: list[LlmDoc],
    mock_search_tool: MagicMock,
    force_use_tool: ForceUseTool,
    expected_tool_args: dict,
) -> None:
    answer_instance.tools = [mock_search_tool]
    answer_instance.force_use_tool = force_use_tool

    # Set up the LLM mock to return search results and then an answer
    mock_llm = cast(Mock, answer_instance.llm)

    stream_side_effect: list[list[BaseMessage]] = []

    if not force_use_tool.force_use:
        tool_call_chunk = AIMessageChunk(content="")
        tool_call_chunk.tool_calls = [
            ToolCall(
                id="search",
                name="search",
                args=expected_tool_args,
            )
        ]
        tool_call_chunk.tool_call_chunks = [
            ToolCallChunk(
                id="search",
                name="search",
                args=json.dumps(expected_tool_args),
                index=0,
            )
        ]
        stream_side_effect.append([tool_call_chunk])

    stream_side_effect.append(
        [
            AIMessageChunk(content="Based on the search results, "),
            AIMessageChunk(content="the answer is abc[1]. "),
            AIMessageChunk(content="This is some other stuff."),
        ],
    )
    mock_llm.stream.side_effect = stream_side_effect

    # Process the output
    output = list(answer_instance.processed_streamed_output)
    print(output)

    # Updated assertions
    assert len(output) == 7
    assert output[0] == ToolCallKickoff(
        tool_name="search", tool_args=expected_tool_args
    )
    assert output[1] == ToolResponse(
        id="final_context_documents",
        response=mock_search_results,
    )
    assert output[2] == ToolCallFinalResult(
        tool_name="search",
        tool_args=expected_tool_args,
        tool_result=[json.loads(doc.model_dump_json()) for doc in mock_search_results],
    )
    assert output[3] == DanswerAnswerPiece(answer_piece="Based on the search results, ")
    expected_citation = CitationInfo(citation_num=1, document_id="doc1")
    assert output[4] == expected_citation
    assert output[5] == DanswerAnswerPiece(
        answer_piece="the answer is abc[[1]](https://example.com/doc1). "
    )
    assert output[6] == DanswerAnswerPiece(answer_piece="This is some other stuff.")

    expected_answer = (
        "Based on the search results, "
        "the answer is abc[[1]](https://example.com/doc1). "
        "This is some other stuff."
    )
    full_answer = "".join(
        piece.answer_piece
        for piece in output
        if isinstance(piece, DanswerAnswerPiece) and piece.answer_piece is not None
    )
    assert full_answer == expected_answer

    assert answer_instance.llm_answer == expected_answer
    assert len(answer_instance.citations) == 1
    assert answer_instance.citations[0] == expected_citation

    # Verify LLM calls
    if not force_use_tool.force_use:
        assert mock_llm.stream.call_count == 2
        first_call, second_call = mock_llm.stream.call_args_list

        # First call should include the search tool definition
        assert len(first_call.kwargs["tools"]) == 1
        assert (
            first_call.kwargs["tools"][0]
            == mock_search_tool.tool_definition.return_value
        )

        # Second call should not include tools (as we're just generating the final answer)
        assert "tools" not in second_call.kwargs or not second_call.kwargs["tools"]
        # Second call should use the returned prompt from build_next_prompt
        assert (
            second_call.kwargs["prompt"]
            == mock_search_tool.build_next_prompt.return_value.build.return_value
        )

        # Verify that tool_definition was called on the mock_search_tool
        mock_search_tool.tool_definition.assert_called_once()
    else:
        assert mock_llm.stream.call_count == 1

        call = mock_llm.stream.call_args_list[0]
        assert (
            call.kwargs["prompt"]
            == mock_search_tool.build_next_prompt.return_value.build.return_value
        )


def test_answer_with_search_no_tool_calling(
    answer_instance: Answer,
    mock_search_results: list[LlmDoc],
    mock_search_tool: MagicMock,
) -> None:
    answer_instance.tools = [mock_search_tool]

    # Set up the LLM mock to return an answer
    mock_llm = cast(Mock, answer_instance.llm)
    mock_llm.stream.return_value = [
        AIMessageChunk(content="Based on the search results, "),
        AIMessageChunk(content="the answer is abc[1]. "),
        AIMessageChunk(content="This is some other stuff."),
    ]

    # Force non-tool calling behavior
    answer_instance.using_tool_calling_llm = False

    # Process the output
    output = list(answer_instance.processed_streamed_output)

    # Assertions
    assert len(output) == 7
    assert output[0] == ToolCallKickoff(
        tool_name="search", tool_args=DEFAULT_SEARCH_ARGS
    )
    assert output[1] == ToolResponse(
        id="final_context_documents",
        response=mock_search_results,
    )
    assert output[2] == ToolCallFinalResult(
        tool_name="search",
        tool_args=DEFAULT_SEARCH_ARGS,
        tool_result=[json.loads(doc.model_dump_json()) for doc in mock_search_results],
    )
    assert output[3] == DanswerAnswerPiece(answer_piece="Based on the search results, ")
    expected_citation = CitationInfo(citation_num=1, document_id="doc1")
    assert output[4] == expected_citation
    assert output[5] == DanswerAnswerPiece(
        answer_piece="the answer is abc[[1]](https://example.com/doc1). "
    )
    assert output[6] == DanswerAnswerPiece(answer_piece="This is some other stuff.")

    expected_answer = (
        "Based on the search results, "
        "the answer is abc[[1]](https://example.com/doc1). "
        "This is some other stuff."
    )
    assert answer_instance.llm_answer == expected_answer
    assert len(answer_instance.citations) == 1
    assert answer_instance.citations[0] == expected_citation

    # Verify LLM calls
    assert mock_llm.stream.call_count == 1
    call_args = mock_llm.stream.call_args

    # Verify that no tools were passed to the LLM
    assert "tools" not in call_args.kwargs or not call_args.kwargs["tools"]

    # Verify that the prompt was built correctly
    assert (
        call_args.kwargs["prompt"]
        == mock_search_tool.build_next_prompt.return_value.build.return_value
    )

    # Verify that get_args_for_non_tool_calling_llm was called on the mock_search_tool
    mock_search_tool.get_args_for_non_tool_calling_llm.assert_called_once_with(
        QUERY, [], answer_instance.llm
    )

    # Verify that the search tool's run method was called
    mock_search_tool.run.assert_called_once()


def test_answer_with_search_call_quotes_enabled(
    answer_instance: Answer,
    mock_search_results: list[LlmDoc],
    mock_search_tool: MagicMock,
) -> None:
    answer_instance.tools = [mock_search_tool]
    answer_instance.force_use_tool = ForceUseTool(
        force_use=False, tool_name="", args=None
    )
    answer_instance.answer_style_config.citation_config = None
    answer_instance.answer_style_config.quotes_config = QuotesConfig()

    # Set up the LLM mock to return search results and then an answer
    mock_llm = cast(Mock, answer_instance.llm)

    tool_call_chunk = AIMessageChunk(content="")
    tool_call_chunk.tool_calls = [
        ToolCall(
            id="search",
            name="search",
            args=DEFAULT_SEARCH_ARGS,
        )
    ]
    tool_call_chunk.tool_call_chunks = [
        ToolCallChunk(
            id="search",
            name="search",
            args=json.dumps(DEFAULT_SEARCH_ARGS),
            index=0,
        )
    ]

    # needs to be short due to the "anti-hallucination" check in QuotesProcessor
    answer_content = "z"
    quote_content = mock_search_results[0].content
    mock_llm.stream.side_effect = [
        [tool_call_chunk],
        [
            AIMessageChunk(
                content=(
                    '{"answer": "'
                    + answer_content
                    + '", "quotes": ["'
                    + quote_content
                    + '"]}'
                )
            ),
        ],
    ]

    # Process the output
    output = list(answer_instance.processed_streamed_output)

    # Assertions
    assert len(output) == 5
    assert output[0] == ToolCallKickoff(
        tool_name="search", tool_args=DEFAULT_SEARCH_ARGS
    )
    assert output[1] == ToolResponse(
        id="final_context_documents",
        response=mock_search_results,
    )
    assert output[2] == ToolCallFinalResult(
        tool_name="search",
        tool_args=DEFAULT_SEARCH_ARGS,
        tool_result=[json.loads(doc.model_dump_json()) for doc in mock_search_results],
    )
    assert output[3] == DanswerAnswerPiece(answer_piece=answer_content)
    assert output[4] == DanswerQuotes(
        quotes=[
            DanswerQuote(
                quote=quote_content,
                document_id=mock_search_results[0].document_id,
                link=mock_search_results[0].link,
                source_type=mock_search_results[0].source_type,
                semantic_identifier=mock_search_results[0].semantic_identifier,
                blurb=mock_search_results[0].blurb,
            )
        ]
    )

    assert answer_instance.llm_answer == answer_content


def test_is_cancelled(answer_instance: Answer) -> None:
    # Set up the LLM mock to return multiple chunks
    mock_llm = Mock()
    answer_instance.llm = mock_llm
    mock_llm.stream.return_value = [
        AIMessageChunk(content="This is the "),
        AIMessageChunk(content="first part."),
        AIMessageChunk(content="This should not be seen."),
    ]

    # Create a mutable object to control is_connected behavior
    connection_status = {"connected": True}
    answer_instance.is_connected = lambda: connection_status["connected"]

    # Process the output
    output = []
    for i, chunk in enumerate(answer_instance.processed_streamed_output):
        output.append(chunk)
        # Simulate disconnection after the second chunk
        if i == 1:
            connection_status["connected"] = False

    assert len(output) == 3
    assert output[0] == DanswerAnswerPiece(answer_piece="This is the ")
    assert output[1] == DanswerAnswerPiece(answer_piece="first part.")
    assert output[2] == StreamStopInfo(stop_reason=StreamStopReason.CANCELLED)

    # Verify that the stream was cancelled
    assert answer_instance.is_cancelled() is True

    # Verify that the final answer only contains the streamed parts
    assert answer_instance.llm_answer == "This is the first part."

    # Verify LLM calls
    mock_llm.stream.assert_called_once()
