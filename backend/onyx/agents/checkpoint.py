"""Versioned execution checkpoints with explicit feature payload schemas."""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from onyx.agents.models import AgentContext, RunProgress, RunSnapshot
from onyx.agents.tools import InputDecision, ToolAnswer
from onyx.llm.models import (
    Message,
    ToolResult,
    UserMessage,
)

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_MESSAGE = TypeAdapter(Message)


class CheckpointBinding(BaseModel):
    """Application identity; validating this record does not authorize access."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    branch_id: str
    context_version: str


class RestoredCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: RunSnapshot
    context: AgentContext
    binding: CheckpointBinding


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    snapshot: dict[str, JsonValue]
    context: dict[str, JsonValue]
    binding: CheckpointBinding


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


class SnapshotCodec:
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

    def decode_message(self, value: JsonValue) -> Message:
        """Decode an identified message, restoring its concrete payload types."""
        raw = _object(value)
        metadata = raw.pop("metadata", None)
        details = raw.pop("details", None)
        message = _MESSAGE.validate_python(raw)
        message.metadata = self.decode_payload(metadata)
        if isinstance(message, ToolResult):
            message.details = self.decode_payload(details)
        elif details is not None:
            raise ValueError("Only tool results can contain details")
        return message

    def _decode_tool_result(self, value: JsonValue) -> ToolResult:
        raw = _object(value)
        metadata = raw.pop("metadata", None)
        details = raw.pop("details", None)
        result = ToolResult.model_validate(raw)
        result.metadata = self.decode_payload(metadata)
        result.details = self.decode_payload(details)
        return result

    def _decode_messages(self, value: JsonValue) -> list[Message]:
        if not isinstance(value, list):
            raise ValueError("Checkpoint messages must be a list")
        return [self.decode_message(item) for item in value]

    def encode_answer(self, answer: ToolAnswer) -> dict[str, JsonValue]:
        data = _dump(answer)
        if answer.result is not None:
            data["result"] = self.encode_message(answer.result)
        return data

    def decode_answer(self, value: JsonValue) -> ToolAnswer:
        encoded = _EncodedAnswer.model_validate(value)
        return ToolAnswer(
            request_id=encoded.request_id,
            decision=encoded.decision,
            result=self._decode_tool_result(encoded.result)
            if encoded.result is not None
            else None,
        )

    def _encode_snapshot(self, snapshot: RunSnapshot) -> dict[str, JsonValue]:
        data = _dump(snapshot)
        data["input_messages"] = [
            self.encode_message(item) for item in snapshot.input_messages
        ]
        data["messages"] = [self.encode_message(item) for item in snapshot.messages]
        data["child_runs"] = [
            self._encode_snapshot(child) for child in snapshot.child_runs
        ]
        if snapshot.progress is not None:
            data["progress"] = self.encode_progress(snapshot.progress)
        return data

    def _decode_snapshot(self, raw: dict[str, JsonValue]) -> RunSnapshot:
        data = dict(raw)
        input_messages = data.pop("input_messages", [])
        messages = data.pop("messages", [])
        children = data.pop("child_runs", [])
        progress = data.pop("progress", None)
        if not isinstance(children, list):
            raise ValueError("Checkpoint children must be a list")
        data["messages"] = []
        snapshot = RunSnapshot.model_validate(data)
        snapshot.input_messages = self._decode_messages(input_messages)
        snapshot.messages = self._decode_messages(messages)
        snapshot.child_runs = [
            self._decode_snapshot(_object(child)) for child in children
        ]
        if progress is not None:
            snapshot.progress = self.decode_progress(progress)
        return snapshot

    def encode_progress(self, progress: RunProgress) -> dict[str, JsonValue]:
        data = _dump(progress)
        data["feature_state"] = self.encode_payload(progress.feature_state)
        data["answers"] = {
            key: self.encode_answer(answer) for key, answer in progress.answers.items()
        }
        data["steering"] = [self.encode_message(item) for item in progress.steering]
        return data

    def decode_progress(self, value: JsonValue) -> RunProgress:
        raw = _object(value)
        feature_state = raw.pop("feature_state", None)
        answers = raw.pop("answers", {})
        steering = raw.pop("steering", [])
        progress = RunProgress.model_validate(raw)
        progress.feature_state = self.decode_payload(feature_state)
        progress.answers = {
            key: self.decode_answer(answer) for key, answer in _object(answers).items()
        }
        for message in self._decode_messages(steering):
            if not isinstance(message, UserMessage):
                raise ValueError("Steering requires user messages")
            progress.steering.append(message)
        return progress

    def encode(
        self,
        snapshot: RunSnapshot,
        context: AgentContext,
        binding: CheckpointBinding,
    ) -> str:
        context_data = _dump(context)
        context_data["messages"] = [
            self.encode_message(item) for item in context.messages
        ]
        return _Envelope(
            snapshot=self._encode_snapshot(snapshot),
            context=context_data,
            binding=binding,
        ).model_dump_json()

    def decode(
        self,
        serialized: str,
        *,
        expected_binding: CheckpointBinding | None = None,
    ) -> RestoredCheckpoint:
        envelope = _Envelope.model_validate_json(serialized)
        if expected_binding is not None and envelope.binding != expected_binding:
            raise ValueError("Checkpoint does not match the selected context")
        context_data = dict(envelope.context)
        messages = context_data.pop("messages", [])
        context = AgentContext.model_validate(context_data)
        context.messages = self._decode_messages(messages)
        return RestoredCheckpoint(
            snapshot=self._decode_snapshot(envelope.snapshot),
            context=context,
            binding=envelope.binding,
        )
