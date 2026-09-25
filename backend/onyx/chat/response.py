"""Convert between live SDK snapshots and detached chat response records."""

from collections.abc import Sequence

from onyx.agents.models import (
    AgentInfo,
    RunState,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.chat.models import ResponseRecord
from onyx.deep_research.models import ResearchConfiguration
from onyx.llm.models import Message, ToolResultMessage


def response_record(
    snapshot: RunState, registrations: Sequence[AgentInfo] = ()
) -> ResponseRecord:
    """Detach accepted content before optional artifact and display processing."""
    metadata = {info.id: info for info in registrations}

    def capture(node: RunState, *, is_root: bool = False) -> ResponseRecord:
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
            input_messages=[_saved_message(message) for message in node.input_messages],
            steps=[_saved_step(step) for step in node.steps],
            answer_step_index=node.answer_step_index,
            child_runs=[capture(child) for child in node.child_runs],
            status=node.status,
            failure=node.failure.model_copy(deep=True) if node.failure else None,
            checkpoint=node.checkpoint.model_copy(deep=True)
            if node.checkpoint
            else None,
        )

    return capture(snapshot, is_root=True)


def response_snapshot(record: ResponseRecord) -> RunState:
    """Restore detached execution state from accepted response content."""
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
        steps=[step.model_copy(deep=True) for step in record.steps],
        answer_step_index=record.answer_step_index,
        child_runs=[response_snapshot(child) for child in record.child_runs],
        status=record.status,
        failure=record.failure.model_copy(deep=True) if record.failure else None,
        checkpoint=record.checkpoint.model_copy(deep=True)
        if record.checkpoint
        else None,
    )


def _saved_message[T: Message](message: T) -> T:
    # Drop application payloads before copying potentially large tool results.
    return message.model_copy(
        update={"metadata": None, "details": None}
        if isinstance(message, ToolResultMessage)
        else {"metadata": None}
    ).model_copy(deep=True)


def _saved_step(step: StepRecord) -> StepRecord:
    return StepRecord(
        message=_saved_message(step.message),
        generation_status=step.generation_status,
        tools={
            call_id: ToolExecutionRecord(
                status=execution.status,
                result=_saved_message(execution.result)
                if execution.result is not None
                else None,
            )
            for call_id, execution in step.tools.items()
        },
    )
