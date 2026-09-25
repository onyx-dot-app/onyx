"""Serialize paused-run state and validate it against saved chat history during restoration."""

import hashlib
import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from onyx.agents.execution_records import RunStatus
from onyx.agents.models import AgentState, ExecutionCheckpoint, RunProgress, RunState
from onyx.agents.tools import HumanToolAnswer, InputDecision
from onyx.chat.llm_step import PromptMetadata
from onyx.chat.models import (
    ChatFeatureState,
    ChatMessageMetadata,
    ChatSearchResult,
    ResponseRecord,
)
from onyx.chat.response import response_snapshot
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.agent import DeepResearchFeatureState
from onyx.deep_research.models import ResearchAgentCallResult, ResearchMessageMetadata
from onyx.deep_research.research_agent import ResearchFeatureState
from onyx.llm.models import GenerationRequestParams, Message, ToolResult
from onyx.tools.models import (
    CustomToolCallSummary,
    FileReadResult,
    LlmBashExecutionResult,
    LlmPythonExecutionResult,
    MemoryUpdated,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class CheckpointBinding(BaseModel):
    """Application identity; validating this record does not authorize access."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    branch_id: str
    context_version: str


def _checkpoint_model_types() -> dict[str, type[BaseModel]]:
    return {
        "chat.state.v1": ChatFeatureState,
        "research.state.v1": ResearchFeatureState,
        "deep_research.state.v1": DeepResearchFeatureState,
        "prompt.metadata.v1": PromptMetadata,
        "chat.metadata.v1": ChatMessageMetadata,
        "chat.search.v1": ChatSearchResult,
        "search.results.v1": SearchDocsResponse,
        "research.metadata.v1": ResearchMessageMetadata,
        "research.result.v1": ResearchAgentCallResult,
        "coding.result.v1": CodingAgentCallResult,
        "tool.custom.v1": CustomToolCallSummary,
        "tool.file_read.v1": FileReadResult,
        "tool.bash.v1": LlmBashExecutionResult,
        "tool.python.v1": LlmPythonExecutionResult,
        "tool.memory.v1": MemoryUpdated,
        "tool.image.v1": FinalImageGenerationResponse,
    }


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    value: dict[str, JsonValue]


class _EncodedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    decision: InputDecision
    result: dict[str, JsonValue] | None = None


def _dump(model: BaseModel, *, exclude: set[str] | None = None) -> dict[str, JsonValue]:
    return _JSON_OBJECT.validate_python(model.model_dump(mode="json", exclude=exclude))


def _object(value: JsonValue) -> dict[str, JsonValue]:
    return _JSON_OBJECT.validate_python(value)


class _CheckpointSerializer:
    """Serialize execution progress and application models with stable type tags.

    Only registered models can be reconstructed from saved data.
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
        data = _dump(message, exclude={"metadata", "details", "cacheable"})
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
        data = _dump(answer, exclude={"result"})
        data["result"] = None
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
        data = _dump(progress, exclude={"human_tool_answers", "feature_state"})
        # Keep checkpoint wire keys independent of Python field names.
        data["pending"] = data.pop("pending_tool_calls")
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


def _digest(context: AgentState, serializer: _CheckpointSerializer) -> str:
    content = "\n".join(
        # The serializer preserves typed metadata that BaseMessage excludes from JSON.
        json.dumps(
            serializer.encode_message(message), sort_keys=True, separators=(",", ":")
        )
        for message in context.messages
    )
    if context.checkpoint is not None:
        content += "\n" + context.checkpoint.model_dump_json()
    return hashlib.sha256(content.encode()).hexdigest()


def _response_digest(response: ResponseRecord) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "steps": [step.model_dump(mode="json") for step in response.steps],
                "answer_step_index": response.answer_step_index,
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
    state: RunState, serializer: _CheckpointSerializer
) -> dict[str, JsonValue]:
    data = _dump(state, exclude={"input_messages", "steps", "progress"})
    data["steps"] = [
        {
            "message": serializer.encode_message(step.message),
            "generation_status": step.generation_status.value,
            "tools": {
                call_id: {
                    "status": execution.status.value,
                    "result": serializer.encode_message(execution.result)
                    if execution.result is not None
                    else None,
                }
                for call_id, execution in step.tools.items()
            },
        }
        for step in state.steps
    ]
    data["input_messages"] = [
        serializer.encode_message(item) for item in state.input_messages
    ]
    data["progress"] = (
        serializer.encode_progress(state.progress)
        if state.progress is not None
        else None
    )
    return data


def serialize_checkpoint(
    checkpoint: ExecutionCheckpoint,
    response: ResponseRecord,
    binding: CheckpointBinding,
) -> ResponseCheckpoint:
    """Build resume data for storage alongside the response and verify it can reconstruct the run."""
    snapshot = checkpoint.run_state
    if snapshot.status != RunStatus.SUSPENDED or snapshot.progress is None:
        raise ValueError("Checkpoint requires a safely suspended run")
    if snapshot.child_runs:
        raise ValueError("Save each child response independently before checkpointing")
    if snapshot.run_id != response.run_id:
        raise ValueError("Checkpoint belongs to another response")
    serializer = _CheckpointSerializer(_checkpoint_model_types())

    def payload(message: Message) -> MessagePayload:
        return MessagePayload(
            metadata=serializer.encode_payload(message.metadata),
            details=serializer.encode_payload(message.details)
            if isinstance(message, ToolResult)
            else None,
            cacheable=message.cacheable,
        )

    data = ResponseCheckpoint(
        history_digest=_digest(checkpoint.agent_state, serializer),
        response_digest=_response_digest(response),
        binding=binding,
        revision=snapshot.revision,
        progress=serializer.encode_progress(snapshot.progress),
        request_params=snapshot.request_params,
        message_payloads=[payload(message) for message in snapshot.messages],
        input_payloads=[payload(message) for message in snapshot.input_messages],
    )
    restored = _restore_checkpoint_state(
        data, response, checkpoint.agent_state, serializer
    )
    if _serialized_run_state(restored.run_state, serializer) != _serialized_run_state(
        snapshot, serializer
    ):
        raise ValueError("Response history cannot reconstruct this checkpoint")
    return data


def deserialize_checkpoint(
    data: ResponseCheckpoint,
    response: ResponseRecord,
    context: AgentState,
    binding: CheckpointBinding,
) -> ExecutionCheckpoint:
    """Validate saved resume data against the selected history and rebuild execution state."""
    serializer = _CheckpointSerializer(_checkpoint_model_types())
    if _digest(context, serializer) != data.history_digest:
        raise ValueError("Checkpoint history changed")
    if _response_digest(response) != data.response_digest:
        raise ValueError("Checkpoint response changed")
    if data.binding != binding:
        raise ValueError("Checkpoint does not match the selected context")
    return _restore_checkpoint_state(data, response, context, serializer)


def _restore_checkpoint_state(
    data: ResponseCheckpoint,
    response: ResponseRecord,
    context: AgentState,
    serializer: _CheckpointSerializer,
) -> ExecutionCheckpoint:
    snapshot = response_snapshot(response)
    snapshot.status = RunStatus.SUSPENDED
    snapshot.revision = data.revision
    snapshot.progress = serializer.decode_progress(data.progress)
    snapshot.request_params = data.request_params

    def restore_payloads(
        messages: list[Message], payloads: list[MessagePayload]
    ) -> None:
        if len(messages) != len(payloads):
            raise ValueError("Checkpoint message boundaries changed")
        for message, payload in zip(messages, payloads, strict=True):
            message.metadata = serializer.decode_payload(payload.metadata)
            message.cacheable = payload.cacheable
            if isinstance(message, ToolResult):
                message.details = serializer.decode_payload(payload.details)
            elif payload.details is not None:
                raise ValueError("Only tool results can have tool details")

    restore_payloads(snapshot.messages, data.message_payloads)
    restore_payloads(snapshot.input_messages, data.input_payloads)
    return ExecutionCheckpoint(agent_state=context.snapshot(), run_state=snapshot)
