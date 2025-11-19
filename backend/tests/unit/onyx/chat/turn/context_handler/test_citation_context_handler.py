"""Unit tests for assign_citation_numbers handler."""

import json
from collections.abc import Sequence
from typing import Union
from uuid import uuid4

from pydantic import TypeAdapter
from pydantic import ValidationError

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import FunctionCallMessage
from onyx.agents.agent_sdk.message_types import FunctionCallOutputMessage
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.turn.context_handler.citation import (
    assign_citation_numbers_recent_tool_calls,
)
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.chat.turn.models import FetchedDocumentCacheEntry
from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmInternalSearchResult,
)
from onyx.tools.tool_implementations_v2.tool_result_models import LlmOpenUrlResult
from onyx.tools.tool_implementations_v2.tool_result_models import LlmWebSearchResult
from tests.unit.onyx.chat.turn.utils import create_test_inference_section

# TypeAdapter for parsing tool results after stripping (no discriminator needed)
_stripped_tool_result_adapter = TypeAdapter(
    list[Union[LlmInternalSearchResult, LlmWebSearchResult, LlmOpenUrlResult]]
)


def _create_test_document(
    unique_identifier_to_strip_away: str, document_citation_number: int
) -> dict:
    return LlmInternalSearchResult(
        unique_identifier_to_strip_away=unique_identifier_to_strip_away,
        document_citation_number=document_citation_number,
        title="test title",
        excerpt="test excerpt",
        metadata={"a": "b"},
    ).model_dump()


def _create_test_open_url_document(
    unique_identifier_to_strip_away: str, document_citation_number: int
) -> dict:
    return LlmOpenUrlResult(
        unique_identifier_to_strip_away=unique_identifier_to_strip_away,
        document_citation_number=document_citation_number,
        content="test content",
    ).model_dump()


def _create_test_web_search_document(
    unique_identifier_to_strip_away: str, document_citation_number: int
) -> dict:
    return LlmWebSearchResult(
        unique_identifier_to_strip_away=unique_identifier_to_strip_away,
        document_citation_number=document_citation_number,
        title="test title",
        snippet="test snippet",
        url="https://test.url",
    ).model_dump()


def _create_dummy_function_call() -> FunctionCallMessage:
    return FunctionCallMessage(
        arguments='{"queries":["cheese"]}',
        name="internal_search",
        call_id="call",
        type="function_call",
        id="__fake_id__",
    )


def _parse_tool_call_result_from_messages(
    messages: Sequence[AgentSDKMessage],
) -> list[LlmInternalSearchResult | LlmOpenUrlResult | LlmWebSearchResult]:
    """Parse LLM documents from messages after citation processing.

    Note: After citation processing, 'type' and 'unique_identifier_to_strip_away'
    fields are stripped from the documents that were newly processed. Documents from
    previous tool calls may still have these fields.
    """
    results: list[LlmInternalSearchResult | LlmOpenUrlResult | LlmWebSearchResult] = []

    for msg in messages:
        if msg.get("type") == "function_call_output":
            func_output_msg: FunctionCallOutputMessage = msg  # type: ignore[assignment]
            output = func_output_msg["output"]
            try:
                docs = json.loads(output)
                for doc in docs:
                    if (
                        doc.get(
                            "document_citation_number",
                            DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                        )
                        != DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                    ):
                        assert "type" not in json.dumps(
                            doc
                        ), "type should not be in processed documents"
                        assert "unique_identifier_to_strip_away" not in json.dumps(
                            doc
                        ), "unique_identifier_to_strip_away should not be in processed documents"
            except (json.JSONDecodeError, AssertionError):
                raise
            except Exception:
                pass

            # Parse using pydantic with non-discriminated union
            # For documents where fields are stripped, pydantic will try each type
            try:
                parsed_results = _stripped_tool_result_adapter.validate_json(output)
                results.extend(parsed_results)
            except ValidationError:
                # If parsing fails, skip this tool call output
                pass

    return results


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
                    _create_test_document(
                        "first", DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                    ),
                    _create_test_document(
                        "second", DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                    ),
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
        fetched_documents_cache={
            "first": FetchedDocumentCacheEntry(
                inference_section=create_test_inference_section(),
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            ),
            "second": FetchedDocumentCacheEntry(
                inference_section=create_test_inference_section(),
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            ),
        },
    )
    result = assign_citation_numbers_recent_tool_calls(messages, context)
    assert result.new_docs_cited == 2
    assert result.num_tool_calls_cited == 1

    message_llm_docs = _parse_tool_call_result_from_messages(result.updated_messages)
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
    )
    result = assign_citation_numbers_recent_tool_calls(messages, context)
    assert result.new_docs_cited == 0
    assert result.num_tool_calls_cited == 0
    message_llm_docs = _parse_tool_call_result_from_messages(result.updated_messages)
    assert len(message_llm_docs) == 0


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
                    _create_test_document(
                        "first", DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                    ),
                    _create_test_document(
                        "second", DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                    ),
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
            output=json.dumps(
                [_create_test_document("third", DOCUMENT_CITATION_NUMBER_EMPTY_VALUE)]
            ),
            call_id="call_2",
            type="function_call_output",
        ),
    ]
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies=chat_turn_dependencies,
        documents_processed_by_citation_context_handler=2,
        tool_calls_processed_by_citation_context_handler=1,
        fetched_documents_cache={
            "first": FetchedDocumentCacheEntry(
                inference_section=create_test_inference_section(),
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            ),
            "second": FetchedDocumentCacheEntry(
                inference_section=create_test_inference_section(),
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            ),
            "third": FetchedDocumentCacheEntry(
                inference_section=create_test_inference_section(),
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            ),
        },
    )
    result = assign_citation_numbers_recent_tool_calls(messages, context)
    assert result.num_tool_calls_cited == 1
    assert result.new_docs_cited == 1
    message_llm_docs = _parse_tool_call_result_from_messages(result.updated_messages)
    assert len(message_llm_docs) == 3
    # In practice, these shouldn't be empty, but we want to make sure we're not interacting
    # with these previous tool call results
    assert (
        message_llm_docs[0].document_citation_number
        == DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
    )
    assert (
        message_llm_docs[1].document_citation_number
        == DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
    )
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
                    _create_test_web_search_document(
                        "a", DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                    ),
                    _create_test_open_url_document(
                        "b", DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                    ),
                ]
            ),
            call_id="call_1",
            type="function_call_output",
        ),
        _create_dummy_function_call(),
        FunctionCallOutputMessage(
            output=json.dumps(
                [_create_test_document("e", DOCUMENT_CITATION_NUMBER_EMPTY_VALUE)]
            ),
            call_id="call_2",
            type="function_call_output",
        ),
    ]
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies=chat_turn_dependencies,
        documents_processed_by_citation_context_handler=0,
        tool_calls_processed_by_citation_context_handler=0,
        fetched_documents_cache={
            "a": FetchedDocumentCacheEntry(
                inference_section=create_test_inference_section(),
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            ),
            "b": FetchedDocumentCacheEntry(
                inference_section=create_test_inference_section(),
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            ),
            "e": FetchedDocumentCacheEntry(
                inference_section=create_test_inference_section(),
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            ),
        },
    )
    result = assign_citation_numbers_recent_tool_calls(messages, context)
    assert result.new_docs_cited == 3
    assert result.num_tool_calls_cited == 2
    # Find the tool message and check citation numbers
    # Pass None to parse all document types (mixed types in parallel tool calls)
    message_llm_docs = _parse_tool_call_result_from_messages(result.updated_messages)

    assert len(message_llm_docs) == 3
    assert message_llm_docs[0].document_citation_number == 1
    assert message_llm_docs[1].document_citation_number == 2
    assert message_llm_docs[2].document_citation_number == 3


def test_assign_reused_citation_numbers(
    chat_turn_dependencies: ChatTurnDependencies,
) -> None:
    unique_identifier_to_strip_away = "b"
    cached_web_search_document = _create_test_web_search_document(
        unique_identifier_to_strip_away, 1
    )
    # already processed so these fields should have been stripped away
    del cached_web_search_document["unique_identifier_to_strip_away"]
    del cached_web_search_document["type"]
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
                    cached_web_search_document,
                ]
            ),
            call_id="call_1",
            type="function_call_output",
        ),
        _create_dummy_function_call(),
        FunctionCallOutputMessage(
            output=json.dumps(
                [
                    _create_test_open_url_document(
                        unique_identifier_to_strip_away,
                        DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                    )
                ]
            ),
            call_id="call_2",
            type="function_call_output",
        ),
    ]
    context = ChatTurnContext(
        chat_session_id=uuid4(),
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies=chat_turn_dependencies,
        documents_processed_by_citation_context_handler=1,
        tool_calls_processed_by_citation_context_handler=1,
        fetched_documents_cache={
            unique_identifier_to_strip_away: FetchedDocumentCacheEntry(
                inference_section=create_test_inference_section(),
                document_citation_number=1,
            ),
        },
    )
    result = assign_citation_numbers_recent_tool_calls(messages, context)
    assert result.new_docs_cited == 0
    message_llm_docs = _parse_tool_call_result_from_messages(result.updated_messages)
    assert len(message_llm_docs) == 2
    assert message_llm_docs[0].document_citation_number == 1
    # Reuse document citation number from cached web search document
    assert message_llm_docs[1].document_citation_number == 1
