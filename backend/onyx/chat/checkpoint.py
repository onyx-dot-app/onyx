"""Supplemental resume data bound to canonical response items and selected history."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from onyx.agents.checkpoint import CheckpointBinding, SnapshotCodec
from onyx.agents.models import AgentContext, ExecutionCheckpoint
from onyx.agents.transcript import RunStatus
from onyx.chat.models import ResponseRecord
from onyx.chat.response import response_snapshot
from onyx.chat.restoration import feature_payload_types
from onyx.llm.models import GenerationRequestParams, Message, ToolResult


class MessagePayload(BaseModel):
    metadata: JsonValue = None
    details: JsonValue = None
    cacheable: bool = False


class ResponseCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    history_digest: str
    response_digest: str
    binding: CheckpointBinding
    revision: int
    progress: dict[str, JsonValue]
    # Request display settings are saved by chat finalization, after execution ends.
    request_params: GenerationRequestParams | None
    message_payloads: list[MessagePayload]
    input_payloads: list[MessagePayload]


def _digest(context: AgentContext, codec: SnapshotCodec) -> str:
    content = "\n".join(
        # The codec preserves typed metadata that BaseMessage excludes from JSON.
        json.dumps(codec.encode_message(message), sort_keys=True, separators=(",", ":"))
        for message in context.messages
    )
    if context.checkpoint is not None:
        content += "\n" + context.checkpoint.model_dump_json()
    return hashlib.sha256(content.encode()).hexdigest()


def _response_digest(response: ResponseRecord) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "items": [item.model_dump(mode="json") for item in response.items],
                "checkpoint": response.checkpoint.model_dump(mode="json")
                if response.checkpoint is not None
                else None,
                "input": [
                    item.model_dump(mode="json") for item in response.input_messages
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def save_checkpoint_data(
    checkpoint: ExecutionCheckpoint,
    response: ResponseRecord,
    binding: CheckpointBinding,
) -> ResponseCheckpoint:
    """Strip canonical message content; retain callback payloads only for resumption."""
    snapshot = checkpoint.snapshot
    if snapshot.status != RunStatus.SUSPENDED or snapshot.progress is None:
        raise ValueError("Checkpoint requires a safely suspended run")
    if snapshot.child_runs:
        raise ValueError("Save each child response independently before checkpointing")
    if snapshot.run_id != response.run_id:
        raise ValueError("Checkpoint belongs to another response")
    codec = SnapshotCodec(feature_payload_types())

    def payload(message: Message) -> MessagePayload:
        return MessagePayload(
            metadata=codec.encode_payload(message.metadata),
            details=codec.encode_payload(message.details)
            if isinstance(message, ToolResult)
            else None,
            cacheable=message.cacheable,
        )

    data = ResponseCheckpoint(
        history_digest=_digest(checkpoint.context, codec),
        response_digest=_response_digest(response),
        binding=binding,
        revision=snapshot.revision,
        progress=codec.encode_progress(snapshot.progress),
        request_params=snapshot.request_params,
        message_payloads=[payload(message) for message in snapshot.messages],
        input_payloads=[payload(message) for message in snapshot.input_messages],
    )
    restored = restore_checkpoint_data(data, response, checkpoint.context, binding)
    if codec.encode(restored.snapshot, restored.context, binding) != codec.encode(
        snapshot, checkpoint.context, binding
    ):
        raise ValueError("Response history cannot reconstruct this checkpoint")
    return data


def restore_checkpoint_data(
    data: ResponseCheckpoint,
    response: ResponseRecord,
    context: AgentContext,
    binding: CheckpointBinding,
) -> ExecutionCheckpoint:
    codec = SnapshotCodec(feature_payload_types())
    if _digest(context, codec) != data.history_digest:
        raise ValueError("Checkpoint history changed")
    if _response_digest(response) != data.response_digest:
        raise ValueError("Checkpoint response changed")
    if data.binding != binding:
        raise ValueError("Checkpoint does not match the selected context")
    snapshot = response_snapshot(response)
    snapshot.status = RunStatus.SUSPENDED
    snapshot.revision = data.revision
    snapshot.progress = codec.decode_progress(data.progress)
    snapshot.request_params = data.request_params

    def restore_payloads(
        messages: list[Message], payloads: list[MessagePayload]
    ) -> None:
        if len(messages) != len(payloads):
            raise ValueError("Checkpoint message boundaries changed")
        for message, payload in zip(messages, payloads, strict=True):
            message.metadata = codec.decode_payload(payload.metadata)
            message.cacheable = payload.cacheable
            if isinstance(message, ToolResult):
                message.details = codec.decode_payload(payload.details)
            elif payload.details is not None:
                raise ValueError("Only tool results can have tool details")

    restore_payloads(snapshot.messages, data.message_payloads)
    restore_payloads(snapshot.input_messages, data.input_payloads)
    return ExecutionCheckpoint(context=context.snapshot(), snapshot=snapshot)
