"""Unit tests for assign_citation_numbers handler."""

import json
from collections.abc import Sequence
from uuid import uuid4

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import FunctionCallMessage
from onyx.agents.agent_sdk.message_types import FunctionCallOutputMessage
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.models import LlmDoc
from onyx.chat.turn.context_handler.citation import (
    assign_citation_numbers_recent_tool_calls,
)
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import ChatTurnDependencies


def _create_test_document(document_id: str, document_citation_number: int) -> dict:
    """Helper to create a test document with minimal boilerplate."""
    return {
        "document_id": document_id,
        "content": "test content",
        "blurb": "test blurb",
        "semantic_identifier": "test_semantic_id",
        "source_type": "linear",
        "metadata": {"a": "b"},
        "updated_at": "2025-08-07T01:01:52Z",
        "link": "https://test.link",
        "source_links": {"0": "https://test.link"},
        "match_highlights": ["test content"],
        "document_citation_number": document_citation_number,
    }


def _create_dummy_function_call() -> FunctionCallMessage:
    return FunctionCallMessage(
        arguments='{"queries":["cheese"]}',
        name="internal_search",
        call_id="call",
        type="function_call",
        id="__fake_id__",
    )


def _parse_llm_docs_from_messages(messages: Sequence[AgentSDKMessage]) -> list[LlmDoc]:
    tool_message_outputs: list[str] = []
    for msg in messages:
        if msg.get("type") == "function_call_output":
            # Type narrow to FunctionCallOutputMessage
            func_output_msg: FunctionCallOutputMessage = msg  # type: ignore[assignment]
            tool_message_outputs.append(func_output_msg["output"])
    return [
        LlmDoc(**doc) for output in tool_message_outputs for doc in json.loads(output)
    ]


def test_assign_citation_numbers_basic(
    chat_turn_dependencies: ChatTurnDependencies,
) -> None:
    messages: list[AgentSDKMessage] = [
        SystemMessage(
            role="system",
            content=[
                InputTextContent(text="\nYou are an assistant.", type="input_text")
            ],
        ),
        UserMessage(
            role="user",
            content=[
                InputTextContent(text="search internally for cheese", type="input_text")
            ],
        ),
        _create_dummy_function_call(),
        FunctionCallOutputMessage(
            output=json.dumps(
                [
                    _create_test_document("first", -1),
                    _create_test_document("second", -1),
                ]
            ),
            call_id="call",
            type="function_call_output",
        ),
    ]
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies=chat_turn_dependencies,
        aggregated_context=AggregatedDRContext(
            context="",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
    )
    result = assign_citation_numbers_recent_tool_calls(messages, context)
    assert result.num_docs_cited == 2
    assert result.num_tool_calls_cited == 1

    message_llm_docs = _parse_llm_docs_from_messages(result.updated_messages)

    # Verify citation numbers were assigned correctly
    assert len(result.new_llm_docs) == 2  # all two documents were cited
    assert len(message_llm_docs) == 2
    assert message_llm_docs[0].document_citation_number == 1
    assert message_llm_docs[1].document_citation_number == 2


def test_assign_citation_numbers_no_relevant_tool_calls(
    chat_turn_dependencies: ChatTurnDependencies,
) -> None:
    messages: list[AgentSDKMessage] = [
        SystemMessage(
            role="system",
            content=[
                InputTextContent(text="\nYou are an assistant.", type="input_text")
            ],
        ),
        UserMessage(
            role="user",
            content=[
                InputTextContent(text="search internally for cheese", type="input_text")
            ],
        ),
        _create_dummy_function_call(),
        FunctionCallOutputMessage(
            output=json.dumps([{"document_id": "x"}]),
            call_id="call",
            type="function_call_output",
        ),
    ]
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies=chat_turn_dependencies,
        aggregated_context=AggregatedDRContext(
            context="",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
    )
    result = assign_citation_numbers_recent_tool_calls(messages, context)
    assert result.num_docs_cited == 0
    assert result.num_tool_calls_cited == 0
    assert len(result.new_llm_docs) == 0


def test_assign_citation_numbers_previous_tool_calls(
    chat_turn_dependencies: ChatTurnDependencies,
) -> None:
    messages: list[AgentSDKMessage] = [
        SystemMessage(
            role="system",
            content=[
                InputTextContent(text="\nYou are an assistant.", type="input_text")
            ],
        ),
        UserMessage(
            role="user",
            content=[
                InputTextContent(text="search internally for cheese", type="input_text")
            ],
        ),
        _create_dummy_function_call(),
        FunctionCallOutputMessage(
            output=json.dumps(
                [
                    _create_test_document("first", -1),
                    _create_test_document("second", -1),
                ]
            ),
            call_id="call_1",
            type="function_call_output",
        ),
        UserMessage(
            role="user",
            content=[
                InputTextContent(
                    text="search internally for cheese again", type="input_text"
                )
            ],
        ),
        _create_dummy_function_call(),
        FunctionCallOutputMessage(
            output=json.dumps([_create_test_document("third", -1)]),
            call_id="call_2",
            type="function_call_output",
        ),
    ]
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies=chat_turn_dependencies,
        aggregated_context=AggregatedDRContext(
            context="",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        documents_cited_count=2,
        tool_calls_cited_count=1,
    )
    result = assign_citation_numbers_recent_tool_calls(messages, context)
    assert len(result.new_llm_docs) == 1  # only one new document was cited
    assert result.num_tool_calls_cited == 1
    assert result.num_docs_cited == 1
    message_llm_docs = _parse_llm_docs_from_messages(result.updated_messages)

    # Verify citation numbers were assigned correctly
    assert len(message_llm_docs) == 3
    # these two should be unchanged
    assert (
        message_llm_docs[0].document_citation_number
        == DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
    )
    assert (
        message_llm_docs[1].document_citation_number
        == DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
    )
    # this one should be assigned
    assert message_llm_docs[2].document_citation_number == 3


def test_assign_citation_numbers_parallel_tool_calls(
    chat_turn_dependencies: ChatTurnDependencies,
) -> None:
    messages: list[AgentSDKMessage] = [
        SystemMessage(
            role="system",
            content=[
                InputTextContent(text="\nYou are an assistant.", type="input_text")
            ],
        ),
        UserMessage(
            role="user",
            content=[
                InputTextContent(text="search internally for cheese", type="input_text")
            ],
        ),
        _create_dummy_function_call(),
        FunctionCallOutputMessage(
            output=json.dumps(
                [
                    _create_test_document("a", -1),
                    _create_test_document("b", -1),
                ]
            ),
            call_id="call_1",
            type="function_call_output",
        ),
        _create_dummy_function_call(),
        FunctionCallOutputMessage(
            output=json.dumps([_create_test_document("e", -1)]),
            call_id="call_2",
            type="function_call_output",
        ),
    ]
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies=chat_turn_dependencies,
        aggregated_context=AggregatedDRContext(
            context="",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        documents_cited_count=0,
        tool_calls_cited_count=0,
    )
    result = assign_citation_numbers_recent_tool_calls(messages, context)
    assert result.num_docs_cited == 3
    assert result.num_tool_calls_cited == 2
    # Find the tool message and check citation numbers
    message_llm_docs = _parse_llm_docs_from_messages(result.updated_messages)

    # Verify citation numbers were assigned correctly
    assert len(result.new_llm_docs) == 3  # all three documents were cited
    assert len(message_llm_docs) == 3
    # these two should be unchanged
    assert message_llm_docs[0].document_citation_number == 1
    assert message_llm_docs[1].document_citation_number == 2
    assert message_llm_docs[2].document_citation_number == 3
