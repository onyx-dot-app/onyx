"""Exercise resume through the response records and checkpoint data stored by chat."""

from collections.abc import Mapping
from unittest.mock import patch

from pydantic import BaseModel, JsonValue, TypeAdapter

from onyx.agents.execution_records import RunStatus
from onyx.agents.models import AgentState, ExecutionCheckpoint, RunState
from onyx.chat.checkpoint import (
    CheckpointBinding,
    CheckpointPayloadCodec,
    ResponseCheckpoint,
    restore_checkpoint_data,
    save_checkpoint_data,
)
from onyx.chat.models import ResponseRecord
from onyx.chat.response import response_record, response_snapshot
from onyx.llm.models import Message, ToolResult


class SavedCheckpoint(BaseModel):
    response: ResponseRecord
    checkpoint: ResponseCheckpoint | None
    history: list[dict[str, JsonValue]]
    context: AgentState
    binding: CheckpointBinding


class CheckpointStorage:
    def __init__(self, payload_types: Mapping[str, type[BaseModel]]) -> None:
        self.payload_types = payload_types
        self.codec = CheckpointPayloadCodec(payload_types)

    def save(
        self, run_state: RunState, agent_state: AgentState, binding: CheckpointBinding
    ) -> str:
        # Child responses are stored independently and resolved through the directory.
        run_state = run_state.model_copy(deep=True, update={"child_runs": []})
        response = response_record(run_state)
        with patch(
            "onyx.chat.checkpoint.feature_payload_types",
            return_value=self.payload_types,
        ):
            checkpoint = (
                save_checkpoint_data(
                    ExecutionCheckpoint(run_state=run_state, agent_state=agent_state),
                    response,
                    binding,
                )
                if run_state.status == RunStatus.SUSPENDED
                else None
            )
        return SavedCheckpoint(
            response=response,
            checkpoint=checkpoint,
            context=agent_state.model_copy(update={"messages": []}),
            history=[
                self.codec.encode_message(message) for message in agent_state.messages
            ],
            binding=binding,
        ).model_dump_json()

    def load(
        self, serialized: str, *, expected_binding: CheckpointBinding | None = None
    ) -> ExecutionCheckpoint:
        saved = SavedCheckpoint.model_validate_json(serialized)
        context = saved.context
        for raw in saved.history:
            metadata = raw.pop("metadata", None)
            details = raw.pop("details", None)
            message = TypeAdapter(Message).validate_python(raw)
            message.metadata = self.codec.decode_payload(metadata)
            if isinstance(message, ToolResult):
                message.details = self.codec.decode_payload(details)
            context.messages.append(message)
        if saved.checkpoint is None:
            return ExecutionCheckpoint(
                agent_state=context, run_state=response_snapshot(saved.response)
            )
        with patch(
            "onyx.chat.checkpoint.feature_payload_types",
            return_value=self.payload_types,
        ):
            return restore_checkpoint_data(
                saved.checkpoint,
                saved.response,
                context,
                expected_binding or saved.binding,
            )
