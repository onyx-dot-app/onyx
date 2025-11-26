"""Citation context handler for assigning sequential citation numbers to documents."""

import json
from collections.abc import Sequence
from typing import Annotated
from typing import Union

from pydantic import BaseModel
from pydantic import Field
from pydantic import TypeAdapter
from pydantic import ValidationError

from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.turn.models import ChatTurnContext
from onyx.llm.message_types import ChatCompletionMessage
from onyx.tools.tool_result_models import LlmInternalSearchResult
from onyx.tools.tool_result_models import LlmOpenUrlResult
from onyx.tools.tool_result_models import LlmWebSearchResult

# Create a tagged union type for all tool results
ToolResult = Annotated[
    Union[LlmInternalSearchResult, LlmWebSearchResult, LlmOpenUrlResult],
    Field(discriminator="type"),
]

# TypeAdapter for parsing tool results
_tool_result_adapter = TypeAdapter(list[ToolResult])


class CitationAssignmentResult(BaseModel):
    updated_messages: list[ChatCompletionMessage]
    new_docs_cited: int
    num_tool_calls_cited: int


def assign_citation_numbers_recent_tool_calls(
    agent_turn_messages: Sequence[ChatCompletionMessage],
    ctx: ChatTurnContext,
) -> CitationAssignmentResult:
    updated_messages: list[ChatCompletionMessage] = []
    docs_fetched_so_far = ctx.documents_processed_by_citation_context_handler
    tool_calls_cited_so_far = ctx.tool_calls_processed_by_citation_context_handler
    num_tool_calls_cited = 0
    new_docs_cited = 0
    curr_tool_call_idx = 0

    for message in agent_turn_messages:
        new_message: ChatCompletionMessage | None = None
        if message.get("role") == "tool":
            if curr_tool_call_idx >= tool_calls_cited_so_far:
                content = str(message.get("content") or "")
                call_id = message.get("tool_call_id", "")
                tool_call_results = _decode_tool_call_result(content)

                if tool_call_results:
                    updated_citation_number = False
                    for result in tool_call_results:
                        if not (
                            result.unique_identifier_to_strip_away is not None
                            and result.document_citation_number
                            == DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                        ):
                            continue
                        updated_citation_number = True
                        cached_document = ctx.fetched_documents_cache[
                            result.unique_identifier_to_strip_away
                        ]
                        if (
                            cached_document.document_citation_number
                            == DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                        ):
                            new_docs_cited += 1
                            result.document_citation_number = (
                                docs_fetched_so_far + new_docs_cited
                            )
                            cached_document.document_citation_number = (
                                result.document_citation_number
                            )
                        else:
                            result.document_citation_number = (
                                cached_document.document_citation_number
                            )
                    if updated_citation_number:
                        updated_output_message: ChatCompletionMessage = {
                            "role": "tool",
                            "content": json.dumps(
                                [
                                    result.model_dump(
                                        mode="json",
                                        exclude={
                                            "unique_identifier_to_strip_away",
                                            "type",
                                        },
                                    )
                                    for result in tool_call_results
                                ]
                            ),
                            "tool_call_id": call_id,
                        }
                        new_message = updated_output_message
                        num_tool_calls_cited += 1

            curr_tool_call_idx += 1

        updated_messages.append(new_message or message)

    return CitationAssignmentResult(
        updated_messages=updated_messages,
        new_docs_cited=new_docs_cited,
        num_tool_calls_cited=num_tool_calls_cited,
    )


def _decode_tool_call_result(
    content: str,
) -> list[LlmInternalSearchResult | LlmOpenUrlResult | LlmWebSearchResult]:
    try:
        return _tool_result_adapter.validate_json(content)
    except ValidationError:
        return []
