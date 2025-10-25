"""Citation context handler for assigning sequential citation numbers to documents."""

import json
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from onyx.chat.models import LlmDoc
from onyx.chat.turn.models import ChatTurnContext


# TODO: Only run this for recently added tool calls
def assign_citation_numbers_recent_tool_calls(
    agent_turn_messages: Sequence[dict[str, Any]],
    ctx: ChatTurnContext,
) -> tuple[Sequence[dict[str, Any]], int, int, list[LlmDoc]]:
    updated_messages = []
    docs_cited_so_far = ctx.documents_cited_count
    tool_calls_cited_so_far = ctx.tool_calls_cited_count
    num_tool_calls_cited = 0
    num_docs_cited = 0
    curr_tool_call_idx = 0
    new_llm_docs: list[LlmDoc] = []
    for message in agent_turn_messages:
        new_message = None
        if message.get("type") == "function_call_output":
            if curr_tool_call_idx >= tool_calls_cited_so_far:
                try:
                    content = message["output"]
                    raw_list = json.loads(content)
                    llm_docs = [LlmDoc(**doc) for doc in raw_list]
                except (json.JSONDecodeError, TypeError, ValidationError):
                    llm_docs = []
                if llm_docs:
                    updated_citation_number = False
                    for doc in llm_docs:
                        if doc.document_citation_number == -1:
                            num_docs_cited += 1  # add 1 first so it's 1-indexed
                            updated_citation_number = True
                            doc.document_citation_number = (
                                docs_cited_so_far + num_docs_cited
                            )
                    if updated_citation_number:
                        new_message = message.copy()
                        new_message["output"] = json.dumps(
                            [doc.model_dump(mode="json") for doc in llm_docs]
                        )
                        num_tool_calls_cited += 1
                        new_llm_docs.extend(llm_docs)
            curr_tool_call_idx += 1
        if new_message is not None:
            updated_messages.append(new_message)
        else:
            updated_messages.append(message)

    return updated_messages, num_docs_cited, num_tool_calls_cited, new_llm_docs
