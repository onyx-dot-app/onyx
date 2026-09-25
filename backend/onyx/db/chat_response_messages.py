import json

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from onyx.agents.compaction import count_tokens
from onyx.agents.models import (
    StepRecord,
    ToolExecutionRecord,
)
from onyx.chat.models import MessageRendering, ResponseRecord
from onyx.configs.constants import MessageType
from onyx.db.models import ChatMessage, ChatResponseCheckpoint, ChatResponseMessage
from onyx.db.models import ToolCall as StoredToolCall
from onyx.llm.models import UserMessage


def read_response_steps(response: ChatMessage) -> list[StepRecord]:
    steps: list[StepRecord] = []
    tools = {
        (tool.turn_number, tool.tool_call_id): tool
        for tool in response.tool_calls or []
    }
    calls: dict[str, str] = {}
    for position, row in enumerate(response.response_messages):
        if row.position != position or row.chat_message_id != response.id:
            raise ValueError("Response message order or ownership is invalid")
        if row.content is not None:
            if row.content.id != row.id or row.step_index != len(steps):
                raise ValueError("Response assistant identity or step is invalid")
            if row.operation_status is None:
                raise ValueError("Assistant message has no operation outcome")
            step = StepRecord(
                message=row.content.model_copy(deep=True),
                generation_status=row.operation_status,
            )
            calls = {call.id: call.name for call in row.content.tool_calls}
            for call in row.content.tool_calls:
                tool = tools.get((row.step_index, call.id))
                if tool is None or tool.tool_name != call.name:
                    raise ValueError(
                        "Assistant tool call has no matching stored invocation"
                    )
                if tool.operation_status is not None:
                    step.tools[call.id] = ToolExecutionRecord(
                        status=tool.operation_status
                    )
            steps.append(step)
            continue
        tool = row.tool_call
        if (
            tool is None
            or tool.parent_chat_message_id != response.id
            or tool.turn_number != len(steps) - 1
            or row.step_index != len(steps) - 1
            or tool.tool_call_id not in calls
            or tool.result is None
            or tool.result.tool_call_id != tool.tool_call_id
            or tool.tool_name != calls.get(tool.tool_call_id)
            or tool.result.tool_name != tool.tool_name
            or tool.tool_call_id not in steps[-1].tools
        ):
            raise ValueError("Response tool result has no matching call")
        del calls[tool.tool_call_id]
        steps[-1].tools[tool.tool_call_id].result = tool.result.model_copy(deep=True)
    return steps


def _invoking_message_id(invocation: StoredToolCall) -> str:
    db_session = object_session(invocation)
    if db_session is None:
        raise ValueError("Tool invocation must be attached to its database session")
    row = db_session.scalar(
        select(ChatResponseMessage).where(
            ChatResponseMessage.chat_message_id == invocation.parent_chat_message_id,
            ChatResponseMessage.step_index == invocation.turn_number,
            ChatResponseMessage.content.is_not(None),
        )
    )
    if (
        row is None
        or row.content is None
        or invocation.tool_call_id not in {call.id for call in row.content.tool_calls}
    ):
        raise ValueError("Tool invocation has no assistant message")
    return row.id


def read_response_record(
    response: ChatMessage,
    agent_path: str,
    *,
    invoking_message_id: str | None = None,
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
    invocation = question.invoking_tool_call
    previous = question.parent_message
    if previous is not None and previous.response_status is None:
        previous = None
    parent_response_id = invocation.parent_chat_message_id if invocation else None
    return ResponseRecord(
        input_messages=[UserMessage(content=question.message)],
        steps=read_response_steps(response),
        answer_step_index=next(
            (row.step_index for row in response.response_messages if row.is_answer),
            None,
        ),
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
        parent_message_id=(invoking_message_id or _invoking_message_id(invocation))
        if invocation
        else None,
    )


def write_response_messages(
    db_session: Session,
    response: ChatMessage,
    record: ResponseRecord,
    presentation: dict[str, MessageRendering],
) -> dict[tuple[str, str], StoredToolCall]:
    """Store message content and invocation records; the caller owns the transaction."""
    tools: dict[tuple[str, str], StoredToolCall] = {}
    existing = {row.id: row for row in response.response_messages}
    stored_tools = {
        (tool.turn_number, tool.tool_call_id): tool
        for tool in response.tool_calls or []
    }
    incoming_ids: set[str] = set()
    next_position = len(existing)
    if record.answer_step_index is not None and not (
        0 <= record.answer_step_index < len(record.steps)
    ):
        raise ValueError("Selected answer is not a recorded step")

    def message_row(message_id: str, step_index: int) -> ChatResponseMessage:
        nonlocal next_position
        if message_id in incoming_ids:
            raise ValueError("Response contains duplicate message identities")
        incoming_ids.add(message_id)
        row = existing.get(message_id) or ChatResponseMessage(
            id=message_id,
            chat_message_id=response.id,
            position=next_position,
            step_index=step_index,
        )
        if row.chat_message_id != response.id or row.step_index != step_index:
            raise ValueError("Response message identity or order changed")
        if message_id not in existing:
            # Resumed tools append rows; model order comes from the assistant's calls.
            next_position += 1
            response.response_messages.append(row)
        return row

    response_tools = response.tool_calls
    if response_tools is None:
        response_tools = []
        response.tool_calls = response_tools
    for step_index, step in enumerate(record.steps):
        message = step.message
        message_id = message.id
        if message_id is None:
            raise ValueError("Saved assistant message has no identity")
        row = message_row(message_id, step_index)
        row.content = message
        row.operation_status = step.generation_status
        row.is_answer = step_index == record.answer_step_index
        setting = presentation.pop(message_id, None)
        if setting is not None:
            row.rendering = setting.model_dump(mode="json")
        if step.tools.keys() - {call.id for call in message.tool_calls}:
            raise ValueError("Tool execution has no call in its assistant message")
        for call in message.tool_calls:
            key = (message_id, call.id)
            if key in tools:
                raise ValueError("Duplicate tool call within one assistant message")
            execution = step.tools.get(call.id)
            tool = stored_tools.get((step_index, call.id)) or StoredToolCall(
                chat_session_id=response.chat_session_id,
                parent_chat_message_id=response.id,
                turn_number=step_index,
                tab_index=len(tools),
                tool_id=None,
                tool_call_id=call.id,
                tool_name=call.name,
                tool_call_arguments=call.arguments,
                argument_error=call.argument_error,
                raw_arguments=call.raw_arguments,
                arguments_complete=call.arguments_complete,
                tool_call_tokens=count_tokens(json.dumps(call.arguments)),
                tool_call_response="",
            )
            tool.tool_call_arguments = call.arguments
            tool.argument_error = call.argument_error
            tool.raw_arguments = call.raw_arguments
            tool.arguments_complete = call.arguments_complete
            tool.operation_status = execution.status if execution is not None else None
            if (step_index, call.id) not in stored_tools:
                response_tools.append(tool)
            db_session.add(tool)
            tools[key] = tool
            if execution is not None and execution.result is not None:
                result = execution.result
                if result.tool_call_id != call.id or result.tool_name != call.name:
                    raise ValueError("Tool result does not match its invocation")
                tool.result = result
                result_row = message_row(f"{message_id}:result:{call.id}", step_index)
                result_row.tool_call = tool
                result_row.is_answer = False
    if existing.keys() - incoming_ids:
        raise ValueError("Response update cannot discard recorded messages")
    db_session.flush()
    return tools


def finish_checkpoint__no_commit(session: Session, message_id: int) -> None:
    row = session.get(ChatResponseCheckpoint, message_id)
    if row is not None:
        session.delete(row)
