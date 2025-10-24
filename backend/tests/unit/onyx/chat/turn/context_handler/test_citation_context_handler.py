"""Unit tests for assign_citation_numbers handler."""

import json
from uuid import uuid4

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
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


def _parse_llm_docs_from_messages(messages: list[dict]) -> list[LlmDoc]:
    tool_message_contents = [
        msg["content"] for msg in messages if msg.get("role") == "tool"
    ]
    return [
        LlmDoc(**doc)
        for content in tool_message_contents
        for doc in json.loads(content)
    ]


def test_assign_citation_numbers_basic(chat_turn_dependencies: ChatTurnDependencies):
    messages = [
        {
            "content": [{"text": "\nYou are an assistant.", "type": "text"}],
            "role": "system",
        },
        {
            "content": [{"text": "search internally for cheese", "type": "text"}],
            "role": "user",
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": '{"queries":["cheese"]}',
                        "name": "internal_search",
                    },
                    "id": "call_lvChvFY5Xs0aw478tZlj2nNd",
                    "type": "function",
                }
            ],
        },
        {
            "content": json.dumps(
                [
                    _create_test_document("first", -1),
                    _create_test_document("second", -1),
                ]
            ),
            "role": "tool",
            "tool_call_id": "call_lvChvFY5Xs0aw478tZlj2nNd",
        },
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
    new_messages, num_docs_cited, num_tool_calls_cited = (
        assign_citation_numbers_recent_tool_calls(messages, context)
    )
    assert num_docs_cited == 2
    assert num_tool_calls_cited == 1
    # Find the tool message and check citation numbers
    tool_message = next(msg for msg in new_messages if msg.get("role") == "tool")
    tool_content_raw = json.loads(tool_message["content"])

    # Parse into LlmDoc objects
    llm_docs = [LlmDoc.model_validate(doc) for doc in tool_content_raw]

    # Verify citation numbers were assigned correctly
    assert len(llm_docs) == 2
    assert llm_docs[0].document_citation_number == 1
    assert llm_docs[1].document_citation_number == 2


def test_assign_citation_numbers_no_relevant_tool_calls(
    chat_turn_dependencies: ChatTurnDependencies,
):
    messages = [
        {
            "content": [{"text": "\nYou are an assistant.", "type": "text"}],
            "role": "system",
        },
        {
            "content": [{"text": "search internally for cheese", "type": "text"}],
            "role": "user",
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": '{"queries":["cheese"]}',
                        "name": "internal_search",
                    },
                    "id": "call_lvChvFY5Xs0aw478tZlj2nNd",
                    "type": "function",
                }
            ],
        },
        {
            "content": json.dumps([{"document_id": "x"}]),
            "role": "tool",
            "tool_call_id": "call_lvChvFY5Xs0aw478tZlj2nNd",
        },
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
    _, num_docs_cited, num_tool_calls_cited = assign_citation_numbers_recent_tool_calls(
        messages, context
    )
    assert num_docs_cited == 0
    assert num_tool_calls_cited == 0


def test_assign_citation_numbers_previous_tool_calls(
    chat_turn_dependencies: ChatTurnDependencies,
):
    messages = [
        {
            "content": [{"text": "\nYou are an assistant.", "type": "text"}],
            "role": "system",
        },
        {
            "content": [{"text": "search internally for cheese", "type": "text"}],
            "role": "user",
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": '{"queries":["cheese"]}',
                        "name": "internal_search",
                    },
                    "id": "call_lvChvFY5Xs0aw478tZlj2nNd",
                    "type": "function",
                }
            ],
        },
        {
            "content": json.dumps(
                [
                    _create_test_document("first", -1),
                    _create_test_document("second", -1),
                ]
            ),
            "role": "tool",
            "tool_call_id": "call_lvChvFY5Xs0aw478tZlj2nNd",
        },
        {
            "content": [{"text": "search internally for cheese again", "type": "text"}],
            "role": "user",
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": '{"queries":["cheese"]}',
                        "name": "internal_search",
                    },
                    "id": "call_lvChvFY5Xs0aw478tZlj2nNd",
                    "type": "function",
                }
            ],
        },
        {
            "content": json.dumps([_create_test_document("third", -1)]),
            "role": "tool",
            "tool_call_id": "call_lvChvFY5Xs0aw478tZlj2nNd",
        },
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
    new_messages, num_docs_cited, num_tool_calls_cited = (
        assign_citation_numbers_recent_tool_calls(messages, context)
    )
    assert num_tool_calls_cited == 1
    assert num_docs_cited == 1
    llm_docs = _parse_llm_docs_from_messages(new_messages)

    # Verify citation numbers were assigned correctly
    assert len(llm_docs) == 3
    # these two should be unchanged
    assert llm_docs[0].document_citation_number == -1
    assert llm_docs[1].document_citation_number == -1
    # this one should be assigned
    assert llm_docs[2].document_citation_number == 3


def test_assign_citation_numbers_parallel_tool_calls(
    chat_turn_dependencies: ChatTurnDependencies,
):
    messages = [
        {
            "content": [{"text": "\nYou are an assistant.", "type": "text"}],
            "role": "system",
        },
        {
            "content": [{"text": "search internally for cheese", "type": "text"}],
            "role": "user",
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": '{"queries":["cheese"]}',
                        "name": "internal_search",
                    },
                    "id": "call_lvChvFY5Xs0aw478tZlj2nNd",
                    "type": "function",
                }
            ],
        },
        {
            "content": json.dumps(
                [
                    _create_test_document("a", -1),
                    _create_test_document("b", -1),
                ]
            ),
            "role": "tool",
            "tool_call_id": "call_lvChvFY5Xs0aw478tZlj2nNd",
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": '{"queries":["cheese"]}',
                        "name": "internal_search",
                    },
                    "id": "call_lvChvFY5Xs0aw478tZlj2nNd",
                    "type": "function",
                }
            ],
        },
        {
            "content": json.dumps([_create_test_document("e", -1)]),
            "role": "tool",
            "tool_call_id": "call_lvChvFY5Xs0aw478tZlj2nNd",
        },
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
    new_messages, num_docs_cited, num_tool_calls_cited = (
        assign_citation_numbers_recent_tool_calls(messages, context)
    )
    assert num_docs_cited == 3
    assert num_tool_calls_cited == 2
    # Find the tool message and check citation numbers
    llm_docs = _parse_llm_docs_from_messages(new_messages)

    # Verify citation numbers were assigned correctly
    assert len(llm_docs) == 3
    # these two should be unchanged
    assert llm_docs[0].document_citation_number == 1
    assert llm_docs[1].document_citation_number == 2
    assert llm_docs[2].document_citation_number == 3
