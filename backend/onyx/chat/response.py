"""Convert between live SDK snapshots and detached chat response records."""

from collections.abc import Sequence

from onyx.agents.coordination import AgentInfo
from onyx.agents.items import (
    ResponseGeneration,
    ResponseToolCall,
    ResponseToolResult,
    answer_message_index,
    messages_from_items,
)
from onyx.agents.models import RunState
from onyx.agents.transcript import OperationSnapshot
from onyx.chat.models import ResponseRecord
from onyx.deep_research.models import ResearchConfiguration
from onyx.llm.models import ToolResultMessage


def response_record(
    snapshot: RunState, registrations: Sequence[AgentInfo] = ()
) -> ResponseRecord:
    """Detach accepted content before optional artifact and display processing."""
    metadata = {info.id: info for info in registrations}

    def capture(node: RunState, *, is_root: bool = False) -> ResponseRecord:
        inputs = [message.model_copy(deep=True) for message in node.input_messages]
        for message in inputs:
            message.metadata = None
            if isinstance(message, ToolResultMessage):
                message.details = None
        items = node.items
        info = metadata.get(node.agent_id) if node.agent_id is not None else None
        if not is_root and info is None:
            raise ValueError("Child response requires its agent registration")
        configuration = info.restoration_config if info else None
        if configuration is not None and not isinstance(
            configuration, ResearchConfiguration
        ):
            raise ValueError("Unsupported saved child configuration")
        return ResponseRecord(
            run_id=node.run_id,
            agent_id=node.agent_id,
            agent_path=info.path if info else "/root",
            agent_description=info.description if info else "",
            restoration_config=configuration.model_copy(deep=True)
            if configuration
            else None,
            previous_run_id=node.previous_run_id,
            parent_run_id=node.parent_run_id,
            parent_tool_call_id=node.parent_tool_call_id,
            parent_message_id=node.parent_message_id,
            input_messages=inputs,
            items=items,
            child_runs=[capture(child) for child in node.child_runs],
            status=node.status,
            failure=node.failure.model_copy(deep=True) if node.failure else None,
            checkpoint=node.checkpoint.model_copy(deep=True)
            if node.checkpoint
            else None,
        )

    return capture(snapshot, is_root=True)


def response_snapshot(record: ResponseRecord) -> RunState:
    """Reconstruct SDK output and operation outcomes from saved response content."""
    operations: list[OperationSnapshot] = []
    message_index = -1
    generation_index = -1
    for item in record.items:
        content = item.content
        if isinstance(content, ResponseGeneration):
            message_index += 1
            generation_index = message_index
            operations.append(
                OperationSnapshot(
                    step_index=item.step_index,
                    message_index=generation_index,
                    status=content.outcome.status,
                )
            )
        elif isinstance(content, ResponseToolResult):
            message_index += 1
        elif isinstance(content, ResponseToolCall) and content.status is not None:
            operations.append(
                OperationSnapshot(
                    step_index=item.step_index,
                    message_index=generation_index,
                    tool_call_id=content.call.id,
                    status=content.status,
                )
            )
    return RunState(
        run_id=record.run_id,
        agent_id=record.agent_id,
        previous_run_id=record.previous_run_id,
        parent_run_id=record.parent_run_id,
        parent_tool_call_id=record.parent_tool_call_id,
        parent_message_id=record.parent_message_id,
        input_messages=[
            message.model_copy(deep=True) for message in record.input_messages
        ],
        messages=messages_from_items(record.items),
        operations=operations,
        answer_message_index=answer_message_index(record.items),
        child_runs=[response_snapshot(child) for child in record.child_runs],
        status=record.status,
        failure=record.failure.model_copy(deep=True) if record.failure else None,
        checkpoint=record.checkpoint.model_copy(deep=True)
        if record.checkpoint
        else None,
    )
