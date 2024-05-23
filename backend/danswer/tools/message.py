import json
from typing import Any

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.messages.tool import ToolMessage
from pydantic import BaseModel

from danswer.llm.utils import get_default_llm_tokenizer


def build_tool_message(
    tool_call: ToolCall, tool_content: str | list[str | dict[str, Any]]
) -> ToolMessage:
    return ToolMessage(
        tool_call_id=tool_call["id"] or "",
        name=tool_call["name"],
        content=tool_content,
    )


class ToolCallSummary(BaseModel):
    tool_call_request: AIMessage
    tool_call_result: ToolMessage


def tool_call_tokens(tool_call_summary: ToolCallSummary) -> int:
    llm_tokenizer = get_default_llm_tokenizer()

    request_tokens = len(
        llm_tokenizer.encode(
            json.dumps(tool_call_summary.tool_call_request.tool_calls[0]["args"])
        )
    )
    result_tokens = len(
        llm_tokenizer.encode(json.dumps(tool_call_summary.tool_call_result.content))
    )

    return request_tokens + result_tokens
