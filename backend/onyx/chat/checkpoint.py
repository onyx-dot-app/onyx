"""Supplemental resume data bound to canonical response items and selected history."""

import hashlib
import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from onyx.agents.execution_records import RunStatus
from onyx.agents.models import AgentState, ExecutionCheckpoint, RunProgress, RunState
from onyx.agents.tools import HumanToolAnswer, InputDecision
from onyx.chat.models import ResponseRecord
from onyx.chat.response import response_snapshot
from onyx.chat.restoration import feature_payload_types
from onyx.llm.models import GenerationRequestParams, Message, ToolResult

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class CheckpointBinding(BaseModel):
    """Application identity; validating this record does not authorize access."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    branch_id: str
    context_version: str


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    value: dict[str, JsonValue]


class _EncodedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    decision: InputDecision
    result: dict[str, JsonValue] | None = None


def _dump(model: BaseModel) -> dict[str, JsonValue]:
    return _JSON_OBJECT.validate_python(model.model_dump(mode="json"))


def _object(value: JsonValue) -> dict[str, JsonValue]:
    return _JSON_OBJECT.validate_python(value)


class CheckpointPayloadCodec:
    """Encode known execution fields and explicitly registered feature payloads.

    Feature schemas own their nested serialization. Unknown payloads fail closed;
    saved data cannot name a Python class or import a decoder.
    """

    def __init__(self, payload_types: Mapping[str, type[BaseModel]]) -> None:
        self._types = dict(payload_types)
        if len(set(self._types.values())) != len(self._types):
            raise ValueError("Each payload type must have one stable tag")
        self._tags = {value: key for key, value in self._types.items()}

    def encode_payload(self, value: BaseModel | None) -> JsonValue:
        if value is None:
            return None
        tag = self._tags.get(type(value))
        if tag is None:
            raise ValueError("Checkpoint contains an unregistered payload type")
        return _dump(_Payload(tag=tag, value=_dump(value)))

    def decode_payload(self, value: JsonValue) -> BaseModel | None:
        if value is None:
            return None
        payload = _Payload.model_validate(value)
        schema = self._types.get(payload.tag)
        if schema is None:
            raise ValueError(f"Unknown checkpoint payload tag: {payload.tag}")
        return schema.model_validate(payload.value)

    def encode_message(self, message: Message | ToolResult) -> dict[str, JsonValue]:
        """Encode a message or answer result with registered feature payloads."""
        data = _dump(message)
        data["metadata"] = self.encode_payload(message.metadata)
        data["cacheable"] = message.cacheable
        if isinstance(message, ToolResult):
            data["details"] = self.encode_payload(message.details)
        return data

    def _decode_tool_result(self, value: JsonValue) -> ToolResult:
        raw = _object(value)
        metadata = raw.pop("metadata", None)
        details = raw.pop("details", None)
        result = ToolResult.model_validate(raw)
        result.metadata = self.decode_payload(metadata)
        result.details = self.decode_payload(details)
        return result

    def encode_answer(self, answer: HumanToolAnswer) -> dict[str, JsonValue]:
        data = _dump(answer)
        if answer.result is not None:
            data["result"] = self.encode_message(answer.result)
        return data

    def decode_answer(self, value: JsonValue) -> HumanToolAnswer:
        encoded = _EncodedAnswer.model_validate(value)
        return HumanToolAnswer(
            request_id=encoded.request_id,
            decision=encoded.decision,
            result=self._decode_tool_result(encoded.result)
            if encoded.result is not None
            else None,
        )

    def encode_progress(self, progress: RunProgress) -> dict[str, JsonValue]:
        data = _dump(progress)
        # Keep checkpoint wire keys independent of Python field names.
        data["pending"] = data.pop("pending_tool_calls")
        data.pop("human_tool_answers")
        data["feature_state"] = self.encode_payload(progress.feature_state)
        data["answers"] = {
            key: self.encode_answer(answer)
            for key, answer in progress.human_tool_answers.items()
        }
        return data

    def decode_progress(self, value: JsonValue) -> RunProgress:
        raw = _object(value)
        feature_state = raw.pop("feature_state", None)
        answers = raw.pop("answers", {})
        raw["pending_tool_calls"] = raw.pop("pending", {})
        progress = RunProgress.model_validate(raw)
        progress.feature_state = self.decode_payload(feature_state)
        progress.human_tool_answers = {
            key: self.decode_answer(answer) for key, answer in _object(answers).items()
        }
        return progress


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


def _digest(context: AgentState, codec: CheckpointPayloadCodec) -> str:
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


def _serialized_run_state(
    state: RunState, codec: CheckpointPayloadCodec
) -> dict[str, JsonValue]:
    data = _dump(state)
    data["input_messages"] = [
        codec.encode_message(item) for item in state.input_messages
    ]
    data["messages"] = [codec.encode_message(item) for item in state.messages]
    if state.progress is not None:
        data["progress"] = codec.encode_progress(state.progress)
    return data


def save_checkpoint_data(
    checkpoint: ExecutionCheckpoint,
    response: ResponseRecord,
    binding: CheckpointBinding,
) -> ResponseCheckpoint:
    """Strip canonical message content; retain callback payloads only for resumption."""
    snapshot = checkpoint.run_state
    if snapshot.status != RunStatus.SUSPENDED or snapshot.progress is None:
        raise ValueError("Checkpoint requires a safely suspended run")
    if snapshot.child_runs:
        raise ValueError("Save each child response independently before checkpointing")
    if snapshot.run_id != response.run_id:
        raise ValueError("Checkpoint belongs to another response")
    codec = CheckpointPayloadCodec(feature_payload_types())

    def payload(message: Message) -> MessagePayload:
        return MessagePayload(
            metadata=codec.encode_payload(message.metadata),
            details=codec.encode_payload(message.details)
            if isinstance(message, ToolResult)
            else None,
            cacheable=message.cacheable,
        )

    data = ResponseCheckpoint(
        history_digest=_digest(checkpoint.agent_state, codec),
        response_digest=_response_digest(response),
        binding=binding,
        revision=snapshot.revision,
        progress=codec.encode_progress(snapshot.progress),
        request_params=snapshot.request_params,
        message_payloads=[payload(message) for message in snapshot.messages],
        input_payloads=[payload(message) for message in snapshot.input_messages],
    )
    restored = restore_checkpoint_data(data, response, checkpoint.agent_state, binding)
    if _serialized_run_state(restored.run_state, codec) != _serialized_run_state(
        snapshot, codec
    ):
        raise ValueError("Response history cannot reconstruct this checkpoint")
    return data


def restore_checkpoint_data(
    data: ResponseCheckpoint,
    response: ResponseRecord,
    context: AgentState,
    binding: CheckpointBinding,
) -> ExecutionCheckpoint:
    codec = CheckpointPayloadCodec(feature_payload_types())
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
    return ExecutionCheckpoint(agent_state=context.snapshot(), run_state=snapshot)
