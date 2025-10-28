"""Citation context handler for assigning sequential citation numbers to documents."""

import json
from collections.abc import Sequence

from pydantic import BaseModel
from pydantic import ValidationError

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import FunctionCallOutputMessage
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.models import LlmDoc
from onyx.chat.turn.models import ChatTurnContext


class CitationAssignmentResult(BaseModel):
    updated_messages: list[AgentSDKMessage]
    num_docs_cited: int
    num_tool_calls_cited: int
    new_llm_docs: list[LlmDoc]


def assign_citation_numbers_recent_tool_calls(
    agent_turn_messages: Sequence[AgentSDKMessage],
    ctx: ChatTurnContext,
) -> CitationAssignmentResult:
    updated_messages: list[AgentSDKMessage] = []
    docs_cited_so_far = ctx.documents_cited_count
    tool_calls_cited_so_far = ctx.tool_calls_cited_count
    num_tool_calls_cited = 0
    num_docs_cited = 0
    curr_tool_call_idx = 0
    new_llm_docs: list[LlmDoc] = []

    for message in agent_turn_messages:
        new_message: AgentSDKMessage | None = None
        if message.get("type") == "function_call_output":
            if curr_tool_call_idx >= tool_calls_cited_so_far:
                # Type narrow to FunctionCallOutputMessage after checking the 'type' field
                func_call_output_msg: FunctionCallOutputMessage = message  # type: ignore[assignment]
                content = func_call_output_msg["output"]
                try:
                    raw_list = json.loads(content)
                    llm_docs = [LlmDoc(**doc) for doc in raw_list]
                except (json.JSONDecodeError, TypeError, ValidationError):
                    llm_docs = []

                if llm_docs:
                    updated_citation_number = False
                    for doc in llm_docs:
                        if (
                            doc.document_citation_number
                            == DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
                        ):
                            num_docs_cited += 1  # add 1 first so it's 1-indexed
                            updated_citation_number = True
                            doc.document_citation_number = (
                                docs_cited_so_far + num_docs_cited
                            )
                    if updated_citation_number:
                        # Create updated function call output message
                        updated_output_message: FunctionCallOutputMessage = {
                            "type": "function_call_output",
                            "call_id": func_call_output_msg["call_id"],
                            "output": json.dumps(
                                [doc.model_dump(mode="json") for doc in llm_docs]
                            ),
                        }
                        new_message = updated_output_message
                        num_tool_calls_cited += 1
                        new_llm_docs.extend(llm_docs)
            # Increment counter for ALL function_call_output messages, not just processed ones
            curr_tool_call_idx += 1

        updated_messages.append(new_message or message)

    return CitationAssignmentResult(
        updated_messages=updated_messages,
        num_docs_cited=num_docs_cited,
        num_tool_calls_cited=num_tool_calls_cited,
        new_llm_docs=new_llm_docs,
    )
