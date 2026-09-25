"""Versioned execution checkpoints with explicit feature payload schemas."""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from onyx.agents.models import AgentState, RunProgress, RunState
from onyx.agents.tools import HumanToolAnswer, InputDecision
from onyx.llm.models import (
    Message,
    ToolResult,
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
    run_state: RunState
    agent_state: AgentState
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

    def _encode_run_state(self, run_state: RunState) -> dict[str, JsonValue]:
        data = _dump(run_state)
        data["input_messages"] = [
            self.encode_message(item) for item in run_state.input_messages
        ]
        data["messages"] = [self.encode_message(item) for item in run_state.messages]
        data["child_runs"] = [
            self._encode_run_state(child) for child in run_state.child_runs
        ]
        if run_state.progress is not None:
            data["progress"] = self.encode_progress(run_state.progress)
        return data

    def _decode_run_state(self, raw: dict[str, JsonValue]) -> RunState:
        data = dict(raw)
        input_messages = data.pop("input_messages", [])
        messages = data.pop("messages", [])
        children = data.pop("child_runs", [])
        progress = data.pop("progress", None)
        if not isinstance(children, list):
            raise ValueError("Checkpoint children must be a list")
        data["messages"] = []
        run_state = RunState.model_validate(data)
        run_state.input_messages = self._decode_messages(input_messages)
        run_state.messages = self._decode_messages(messages)
        run_state.child_runs = [
            self._decode_run_state(_object(child)) for child in children
        ]
        if progress is not None:
            run_state.progress = self.decode_progress(progress)
        return run_state

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

    def encode(
        self,
        run_state: RunState,
        agent_state: AgentState,
        binding: CheckpointBinding,
    ) -> str:
        agent_state_data = _dump(agent_state)
        agent_state_data["messages"] = [
            self.encode_message(item) for item in agent_state.messages
        ]
        return _Envelope(
            snapshot=self._encode_run_state(run_state),
            context=agent_state_data,
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
        agent_state_data = dict(envelope.context)
        messages = agent_state_data.pop("messages", [])
        agent_state = AgentState.model_validate(agent_state_data)
        agent_state.messages = self._decode_messages(messages)
        return RestoredCheckpoint(
            run_state=self._decode_run_state(envelope.snapshot),
            agent_state=agent_state,
            binding=envelope.binding,
        )
