import json

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, object_session

from onyx.agents.compaction import count_tokens
from onyx.agents.items import (
    ResponseGeneration,
    ResponseItem,
    ResponseItemKind,
    ResponseReasoning,
    ResponseText,
    ResponseToolCall,
    ResponseToolResult,
)
from onyx.chat.models import MessageRendering, ResponseRecord
from onyx.configs.constants import MessageType
from onyx.db.models import ChatMessage, ChatResponseItem, StoredResponseContent
from onyx.db.models import ToolCall as StoredToolCall
from onyx.llm.models import ToolCall, UserMessage


def read_response_items(response: ChatMessage) -> list[ResponseItem]:
    items: list[ResponseItem] = []
    for position, row in enumerate(response.response_items):
        if row.position != position or row.chat_message_id != response.id:
            raise ValueError("Response item order or ownership is invalid")
        if row.kind in (
            ResponseItemKind.GENERATION,
            ResponseItemKind.TEXT,
            ResponseItemKind.REASONING,
        ):
            if row.content is None or row.content.value.kind != row.kind:
                raise ValueError("Response item content does not match its kind")
            content = row.content.value
        else:
            tool = row.tool_call
            if (
                tool is None
                or tool.parent_chat_message_id != response.id
                or tool.tool_name is None
            ):
                raise ValueError("Response tool is unavailable")
            if row.kind == ResponseItemKind.TOOL_CALL:
                content = ResponseToolCall(
                    call=ToolCall(
                        id=tool.tool_call_id,
                        name=tool.tool_name,
                        arguments=tool.tool_call_arguments,
                        argument_error=tool.argument_error,
                        raw_arguments=tool.raw_arguments,
                        arguments_complete=tool.arguments_complete,
                    ),
                    status=tool.operation_status,
                )
            else:
                if tool.result is None:
                    raise ValueError("Response tool result is missing")
                content = ResponseToolResult(result=tool.result)
        items.append(
            ResponseItem(
                id=row.id,
                step_index=row.step_index,
                content=content,
            )
        )
    return items


def _invoking_generation_id(invocation: StoredToolCall) -> str:
    db_session = object_session(invocation)
    if db_session is None:
        raise ValueError("Tool invocation must be attached to its database session")
    call = aliased(ChatResponseItem)
    generation_id = db_session.scalar(
        select(ChatResponseItem.id)
        .join(
            call,
            (call.chat_message_id == ChatResponseItem.chat_message_id)
            & (call.step_index == ChatResponseItem.step_index),
        )
        .where(
            call.tool_call_id == invocation.id,
            call.kind == ResponseItemKind.TOOL_CALL,
            ChatResponseItem.kind == ResponseItemKind.GENERATION,
        )
    )
    if generation_id is None:
        raise ValueError("Tool invocation has no generation item")
    return generation_id


def read_response_record(
    response: ChatMessage,
    agent_path: str,
    *,
    invoking_generation_id: str | None = None,
) -> ResponseRecord:
    if response.response_status is None:
        raise ValueError("Response has no saved outcome")
    question = response.parent_message
    if (
        question is None
        or question.message_type != MessageType.USER
        or question.chat_session_id != response.chat_session_id
    ):
        raise ValueError("Response has no question in its conversation")
    items = read_response_items(response)
    invocation = question.invoking_tool_call
    previous = question.parent_message
    if previous is not None and previous.response_status is None:
        previous = None
    parent_response_id = invocation.parent_chat_message_id if invocation else None
    return ResponseRecord(
        input_messages=[UserMessage(content=question.message)],
        items=items,
        status=response.response_status,
        failure=response.response_failure,
        agent_id=str(response.chat_session_id),
        agent_path=agent_path,
        agent_description=response.chat_session.description or ""
        if response.chat_session.spawned_by_message_id is not None
        else "",
        restoration_config=response.chat_session.restoration_config,
        run_id=str(response.id),
        previous_run_id=str(previous.id) if previous else None,
        parent_run_id=str(parent_response_id) if parent_response_id else None,
        parent_tool_call_id=invocation.tool_call_id if invocation else None,
        parent_message_id=(
            invoking_generation_id or _invoking_generation_id(invocation)
        )
        if invocation
        else None,
    )


def write_response_items(
    db_session: Session,
    response: ChatMessage,
    items: list[ResponseItem],
    presentation: dict[str, MessageRendering],
) -> dict[tuple[str, str], StoredToolCall]:
    """Save accepted output and its tool records; the caller owns the transaction."""
    tools: dict[tuple[str, str], StoredToolCall] = {}
    generation_id: str | None = None
    for position, item in enumerate(items):
        content = item.content
        row = ChatResponseItem(
            id=item.id,
            chat_message_id=response.id,
            position=position,
            step_index=item.step_index,
            kind=content.kind,
        )
        if isinstance(content, ResponseGeneration):
            generation_id = item.id
            setting = presentation.pop(item.id, None)
            row.rendering = setting.model_dump(mode="json") if setting else None
        if isinstance(content, (ResponseGeneration, ResponseText, ResponseReasoning)):
            row.content = StoredResponseContent(value=content)
        elif isinstance(content, ResponseToolCall):
            if generation_id is None:
                raise ValueError("Tool call has no generation")
            key = (generation_id, content.call.id)
            if key in tools:
                raise ValueError("Duplicate tool call within one generation")
            tool = StoredToolCall(
                chat_session_id=response.chat_session_id,
                parent_chat_message_id=response.id,
                turn_number=item.step_index,
                tab_index=len(tools),
                tool_id=None,
                tool_call_id=content.call.id,
                tool_name=content.call.name,
                tool_call_arguments=content.call.arguments,
                argument_error=content.call.argument_error,
                raw_arguments=content.call.raw_arguments,
                arguments_complete=content.call.arguments_complete,
                tool_call_tokens=count_tokens(json.dumps(content.call.arguments)),
                tool_call_response="",
                operation_status=content.status,
            )
            db_session.add(tool)
            db_session.flush()
            row.tool_call_id = tool.id
            tools[key] = tool
        else:
            tool = tools.get((generation_id or "", content.result.tool_call_id))
            if tool is None:
                raise ValueError("Tool result has no call in its generation")
            tool.result = content.result
            row.tool_call_id = tool.id
        response.response_items.append(row)
    db_session.flush()
    return tools
