"""Build bounded model context without changing recorded execution output."""

import hashlib
import json
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tiktoken import Encoding

from pydantic import BaseModel, Field

from onyx.agents.transcript import CompactionCheckpoint, completed_tool_call_ids
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    ImageContentPart,
    Message,
    ReasoningEffort,
    SystemMessage,
    ToolChoiceOptions,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.compression_prompts import AGENT_COMPACTION_PROMPT
from onyx.tracing.flows import LLMFlow

INPUT_SAFETY_RATIO = 0.9
COMPACTION_TRIGGER_RATIO = 0.85
RECENT_CONTEXT_RATIO = 0.2
SUMMARY_OUTPUT_LIMIT = 2048
MAX_SUMMARY_BATCHES = 32
SUMMARY_TIMEOUT_SECONDS = 180
MESSAGE_OVERHEAD_TOKENS = 8
IMAGE_TOKEN_ESTIMATE = 2048


class ContextLimitError(ValueError):
    """Required input cannot fit the configured model input limit."""


class ContextBudget(BaseModel):
    input_limit: int = Field(gt=0)
    trigger: int = Field(gt=0)
    recent: int = Field(gt=0)
    summary: int = Field(gt=0)


@lru_cache(maxsize=1)
def _encoder() -> "Encoding":
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text, disallowed_special=()))


def message_tokens(message: Message) -> int:
    count = count_tokens(message.text) + MESSAGE_OVERHEAD_TOKENS
    if isinstance(message, AssistantMessage):
        count += count_tokens(message.thinking)
        count += sum(
            count_tokens(call.model_dump_json()) for call in message.tool_calls
        )
    elif isinstance(message, (UserMessage, ToolResultMessage)) and not isinstance(
        message.content, str
    ):
        count += sum(
            IMAGE_TOKEN_ESTIMATE
            for part in message.content
            if isinstance(part, ImageContentPart)
        )
    return count


def request_tokens(request: GenerationRequest) -> int:
    return (
        count_tokens(request.system_prompt)
        + sum(count_tokens(tool.model_dump_json()) for tool in request.tools)
        + sum(message_tokens(message) for message in request.messages)
    )


def context_budget(model: LLM) -> ContextBudget:
    # max_input_tokens is already an input ceiling, not the total context window.
    limit = max(1, int(model.info.max_input_tokens * INPUT_SAFETY_RATIO))
    return ContextBudget(
        input_limit=limit,
        trigger=max(1, int(limit * COMPACTION_TRIGGER_RATIO)),
        recent=max(1, int(limit * RECENT_CONTEXT_RATIO)),
        summary=max(1, min(SUMMARY_OUTPUT_LIMIT, limit // 8)),
    )


def history_digest(messages: list[Message]) -> str:
    digest = hashlib.sha256()
    for message in messages:
        data = message.model_dump(mode="json", exclude={"details", "metadata", "id"})
        digest.update(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def checkpoint_matches(
    messages: list[Message], checkpoint: CompactionCheckpoint
) -> bool:
    return (
        checkpoint.covered_count <= len(messages)
        and history_digest(messages[: checkpoint.covered_count])
        == checkpoint.covered_digest
    )


def working_messages(
    messages: list[Message], checkpoint: CompactionCheckpoint | None
) -> list[Message]:
    if checkpoint is None:
        return list(messages)
    if not checkpoint_matches(messages, checkpoint):
        raise ValueError("Compaction checkpoint does not match its source history")
    prefix = messages[: checkpoint.covered_count]
    retained: list[Message] = [m for m in prefix if isinstance(m, SystemMessage)]
    retained.append(
        SystemMessage(content=f"Conversation summary:\n{checkpoint.summary}")
    )
    latest_user = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], UserMessage)
        ),
        None,
    )
    if latest_user is not None and latest_user < checkpoint.covered_count:
        retained.append(messages[latest_user])
    return retained + messages[checkpoint.covered_count :]


def _history_boundaries(messages: list[Message]) -> list[int]:
    boundaries: list[int] = []
    pending: set[str] = set()
    for index, message in enumerate(messages):
        if isinstance(message, AssistantMessage):
            pending = {
                call.id for call in message.tool_calls
            } & completed_tool_call_ids(messages, index)
        elif isinstance(message, ToolResultMessage):
            pending.discard(message.tool_call_id)
        if not pending:
            boundaries.append(index + 1)
    return boundaries


class _SummaryInput:
    def __init__(self, messages: list[Message]) -> None:
        self.messages = iter(messages)
        self.message: Message | None = None
        self.tokens: list[int] = []
        self.offset = 0
        self._advance()

    def _advance(self) -> None:
        self.message = next(self.messages, None)
        self.offset = 0
        if self.message is None:
            self.tokens = []
            return
        text = self.message.text
        if isinstance(self.message, AssistantMessage):
            text += "\n" + "\n".join(
                call.model_dump_json() for call in self.message.tool_calls
            )
        self.tokens = _encoder().encode(text, disallowed_special=())

    def take(self, available: int) -> str:
        parts: list[str] = []
        while self.message is not None:
            source = self.message.role.value
            if isinstance(self.message, ToolResultMessage):
                source += f" {self.message.tool_name} ({self.message.tool_call_id})"
            header = f"{source} [continued]:\n" if self.offset else f"{source}:\n"
            available -= count_tokens(header) + 2
            if available <= 0:
                break
            end = min(len(self.tokens), self.offset + available)
            text = ""
            # A token boundary can split a UTF-8 character.
            while end > self.offset:
                try:
                    text = (
                        _encoder()
                        .decode_bytes(self.tokens[self.offset : end])
                        .decode("utf-8")
                    )
                    break
                except UnicodeDecodeError:
                    end -= 1
            if end == self.offset and self.tokens:
                break
            parts.append(header + text)
            available -= end - self.offset
            self.offset = end
            if self.offset == len(self.tokens):
                self._advance()
        return "\n\n".join(parts)


def compact_history(
    model: LLM,
    history: list[Message],
    previous: CompactionCheckpoint | None,
    execution: GenerationContext,
) -> CompactionCheckpoint:
    budget = context_budget(model)
    start = previous.covered_count if previous else 0
    boundaries = [end for end in _history_boundaries(history) if end > start]
    if not boundaries:
        raise ContextLimitError("No completed history is available for compaction")
    cutoff = boundaries[-1]
    tail_tokens = 0
    tail_end = len(history)
    for end in reversed(boundaries):
        tail_tokens += sum(message_tokens(message) for message in history[end:tail_end])
        tail_end = end
        if tail_tokens > budget.recent:
            break
        cutoff = end
    summary = previous.summary if previous else ""
    input_budget = (
        budget.input_limit - budget.summary - count_tokens(AGENT_COMPACTION_PROMPT)
    )
    if input_budget <= 0:
        raise ContextLimitError("The model input limit is too small for a summary")
    source = _SummaryInput(history[start:cutoff])
    for _ in range(MAX_SUMMARY_BATCHES):
        if source.message is None:
            break
        available = (
            input_budget
            - count_tokens(summary)
            - MESSAGE_OVERHEAD_TOKENS
            - count_tokens("Previous summary:\n\nHistory:\n")
        )
        if available <= 0:
            raise ContextLimitError("The summary leaves no room for history")
        batch = source.take(available)
        if not batch:
            raise ContextLimitError(
                "A summary source label exceeds the available input"
            )
        if execution.cancellation:
            execution.cancellation.check()
        response = model.invoke(
            GenerationRequest(
                system_prompt=AGENT_COMPACTION_PROMPT,
                messages=[
                    UserMessage(
                        content=f"Previous summary:\n{summary}\n\nHistory:\n{batch}"
                    )
                ],
                options=GenerationOptions(
                    max_tokens=budget.summary,
                    tool_choice=ToolChoiceOptions.NONE,
                    reasoning_effort=ReasoningEffort.OFF,
                ),
            ),
            execution.model_copy(
                update={
                    "flow": LLMFlow.CHAT_HISTORY_SUMMARIZATION,
                    "total_timeout": min(
                        execution.total_timeout or SUMMARY_TIMEOUT_SECONDS,
                        SUMMARY_TIMEOUT_SECONDS,
                    ),
                }
            ),
        )
        if not response.text.strip() or response.stop_reason in {"error", "aborted"}:
            raise ContextLimitError("The model did not produce a usable summary")
        summary = response.text.strip()
    if source.message is not None:
        raise ContextLimitError("History exceeds the bounded summary workload")
    checkpoint = CompactionCheckpoint(
        summary=summary,
        covered_count=cutoff,
        covered_digest=history_digest(history[:cutoff]),
    )
    before = sum(message_tokens(m) for m in working_messages(history, previous))
    after = sum(message_tokens(m) for m in working_messages(history, checkpoint))
    if after >= before:
        raise ContextLimitError("Compaction did not reduce the model context")
    return checkpoint
