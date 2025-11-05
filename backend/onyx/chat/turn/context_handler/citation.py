"""Citation context handler for assigning sequential citation numbers to documents."""

import json
from collections.abc import Sequence

from pydantic import BaseModel
from pydantic import ValidationError

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import FunctionCallOutputMessage
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.turn.models import ChatTurnContext
from onyx.tools.tool_implementations_v2.internal_search import LlmInternalSearchResult
from onyx.tools.tool_implementations_v2.web import LlmOpenUrlResult
from onyx.tools.tool_implementations_v2.web import LlmWebSearchResult


class CitationAssignmentResult(BaseModel):
    updated_messages: list[AgentSDKMessage]
    new_docs_cited: int
    num_tool_calls_cited: int


def assign_citation_numbers_recent_tool_calls(
    agent_turn_messages: Sequence[AgentSDKMessage],
    ctx: ChatTurnContext,
) -> CitationAssignmentResult:
    updated_messages: list[AgentSDKMessage] = []
    docs_fetched_so_far = ctx.documents_processed_by_citation_context_handler
    tool_calls_cited_so_far = ctx.tool_calls_processed_by_citation_context_handler
    num_tool_calls_cited = 0
    new_docs_cited = 0
    curr_tool_call_idx = 0

    for message in agent_turn_messages:
        new_message: AgentSDKMessage | None = None
        if message.get("type") == "function_call_output":
            if curr_tool_call_idx >= tool_calls_cited_so_far:
                # Type narrow to FunctionCallOutputMessage after checking the 'type' field
                func_call_output_msg: FunctionCallOutputMessage = message  # type: ignore[assignment]
                content = func_call_output_msg["output"]
                tool_call_results = _decode_tool_call_result(content)

                if tool_call_results:
                    updated_citation_number = False
                    for result in tool_call_results:
                        if (
                            result.document_citation_number
                            == DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                        ):
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
                        updated_output_message: FunctionCallOutputMessage = {
                            "type": "function_call_output",
                            "call_id": func_call_output_msg["call_id"],
                            "output": json.dumps(
                                [
                                    result.model_dump(
                                        mode="json",
                                        exclude={"unique_identifier_to_strip_away"},
                                    )
                                    for result in tool_call_results
                                ]
                            ),
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


# TODO: Is there a better way to do this?
def _decode_tool_call_result(
    content: str,
) -> list[LlmInternalSearchResult | LlmOpenUrlResult | LlmWebSearchResult]:
    tool_call_results: list[
        LlmInternalSearchResult | LlmOpenUrlResult | LlmWebSearchResult
    ] = []
    try:
        raw_list = json.loads(content)
        # Parse each document individually to support mixed types in the same list
        for doc in raw_list:
            # Try LlmInternalSearchResult first
            try:
                tool_call_results.append(LlmInternalSearchResult(**doc))  # type: ignore[misc]
                continue
            except (TypeError, ValidationError):
                pass

            # Try LlmWebSearchResult next
            try:
                tool_call_results.append(LlmWebSearchResult(**doc))  # type: ignore[misc]
                continue
            except (TypeError, ValidationError):
                pass

            # Try LlmOpenUrlResult finally
            try:
                tool_call_results.append(LlmOpenUrlResult(**doc))  # type: ignore[misc]
                continue
            except (TypeError, ValidationError):
                pass

            # If none of the types match, skip this document
    except (json.JSONDecodeError, TypeError):
        tool_call_results = []
    return tool_call_results
