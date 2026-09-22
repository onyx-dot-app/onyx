"""Map native Pydantic AI compaction results to persisted conversation branches."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai import messages as pm
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai_harness.compaction import (
    SummarizingCompaction,
    TieredCompaction,
    compact_now,
    drain_summary_events,
    estimate_token_count,
)

from onyx.configs.chat_configs import COMPRESSION_TRIGGER_RATIO
from onyx.configs.constants import MessageType
from onyx.db.chat_compaction import find_summary_for_branch, persist_summary
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.tools import get_tools
from onyx.llm.interfaces import LLM
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import ChatTraceMetadata, ensure_trace
from onyx.tracing.llm_utils import llm_generation_span, record_native_llm_response
from onyx.utils.logger import setup_logger

logger = setup_logger()
_SUMMARY_PREFIX = "Summary of previous conversation:\n\n"


@dataclass(frozen=True)
class CompressionResult:
    summary_created: bool
    messages_summarized: int
    error: str | None = None


def native_branch_history(
    history: list[ChatMessage],
    existing_summary: ChatMessage | None,
    tool_names: dict[int, str],
) -> list[pm.ModelMessage]:
    """Carry database row IDs through native compaction for branch cutoffs."""
    result: list[pm.ModelMessage] = []
    cutoff = existing_summary.last_summarized_message_id if existing_summary else None
    if existing_summary:
        text = existing_summary.message
        if not text.startswith(_SUMMARY_PREFIX):
            text = _SUMMARY_PREFIX + text
        result.append(pm.ModelRequest(parts=[pm.SystemPromptPart(text)]))
    for row in history:
        if cutoff is not None and row.id <= cutoff:
            continue
        metadata = {"onyx_message_id": row.id}
        if row.message_type == MessageType.USER:
            result.append(
                pm.ModelRequest(
                    parts=[pm.UserPromptPart(row.message)], metadata=metadata
                )
            )
        elif row.message_type == MessageType.ASSISTANT:
            calls = row.tool_calls or []
            if calls:
                result.append(
                    pm.ModelResponse(
                        parts=[
                            pm.ToolCallPart(
                                call.tool_name or tool_names.get(call.tool_id, "tool"),
                                call.tool_call_arguments,
                                call.tool_call_id,
                            )
                            for call in calls
                        ],
                        metadata=metadata,
                    )
                )
                result.append(
                    pm.ModelRequest(
                        parts=[
                            pm.ToolReturnPart(
                                call.tool_name or tool_names.get(call.tool_id, "tool"),
                                call.tool_call_response or "",
                                call.tool_call_id,
                            )
                            for call in calls
                        ],
                        metadata=metadata,
                    )
                )
            result.append(
                pm.ModelResponse(parts=[pm.TextPart(row.message)], metadata=metadata)
            )
    return result


async def compact_branch(
    messages: list[pm.ModelMessage],
    *,
    llm: LLM,
    input_budget: int,
    tokenizer: Callable[[str], int],
) -> list[pm.ModelMessage]:
    """Native strategies own triggering, safe splitting, and incremental summaries."""
    latest_user = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], pm.ModelRequest)
            and any(
                isinstance(part, pm.UserPromptPart) for part in messages[index].parts
            )
        ),
        None,
    )
    if latest_user is None:
        return messages
    keep_tokens = max(
        1,
        int(input_budget * 0.2),
        estimate_token_count(messages[latest_user:], tokenizer),
    )

    class SummaryModel(WrapperModel):
        @asynccontextmanager
        async def request_stream(
            self,
            messages: list[pm.ModelMessage],
            model_settings: ModelSettings | None,
            model_request_parameters: ModelRequestParameters,
            run_context: RunContext[Any] | None = None,
        ) -> AsyncIterator[StreamedResponse]:
            with llm_generation_span(
                llm=llm,
                flow=LLMFlow.CHAT_HISTORY_SUMMARIZATION,
                input_messages=messages,
            ) as span:
                async with self.wrapped.request_stream(
                    messages, model_settings, model_request_parameters, run_context
                ) as response:
                    try:
                        yield response
                    finally:
                        record_native_llm_response(span, response.get())
                        await asyncio.to_thread(llm.record_usage, response.usage)

    model = SummaryModel(llm.model)
    strategy = TieredCompaction[None](
        tiers=[
            SummarizingCompaction[None](
                max_tokens=input_budget,
                keep_tokens=keep_tokens,
                preserve_first_user_message=False,
                tokenizer=tokenizer,
                model_settings=llm.model_settings(),
                event_stream_handler=drain_summary_events,
            )
        ],
        target_tokens=max(1, int(input_budget * COMPRESSION_TRIGGER_RATIO)),
        tokenizer=tokenizer,
    )
    async with model:
        return await compact_now(strategy, messages, model=model, tokenizer=tokenizer)


def compress_chat_history(
    chat_history: list[ChatMessage],
    llm: LLM,
    *,
    max_input_tokens: int,
    reserved_tokens: int,
) -> CompressionResult:
    if not chat_history:
        return CompressionResult(False, 0)
    session_id = chat_history[0].chat_session_id
    try:
        with get_session_with_current_tenant() as session:
            summary = find_summary_for_branch(session, chat_history)
            names = {tool.id: tool.name for tool in get_tools(session)}
            history = native_branch_history(chat_history, summary, names)
        tokenizer = get_tokenizer(None, None)

        def count(text: str) -> int:
            return len(tokenizer.encode(text))

        with ensure_trace(
            "chat_history_compression",
            group_id=str(session_id),
            metadata=ChatTraceMetadata(chat_session_id=str(session_id)).model_dump(),
        ):
            with asyncio.Runner() as runner:
                compacted = runner.run(
                    compact_branch(
                        history,
                        llm=llm,
                        input_budget=max(1, max_input_tokens - reserved_tokens),
                        tokenizer=count,
                    )
                )
        retained = {id(message) for message in compacted}
        removed = [
            message
            for message in history
            if id(message) not in retained
            and message.metadata
            and "onyx_message_id" in message.metadata
        ]
        remaining_ids = {
            message.metadata["onyx_message_id"]
            for message in compacted
            if message.metadata and "onyx_message_id" in message.metadata
        }
        removed_ids = {
            message.metadata["onyx_message_id"]
            for message in removed
            if message.metadata
        } - remaining_ids
        if not removed_ids:
            return CompressionResult(False, 0)
        new_summary = next(
            (
                part.content
                for message in compacted
                if isinstance(message, pm.ModelRequest)
                for part in message.parts
                if isinstance(part, pm.SystemPromptPart)
                and part.content.startswith(_SUMMARY_PREFIX)
            ),
            None,
        )
        if not new_summary or not new_summary.removeprefix(_SUMMARY_PREFIX).strip():
            raise ValueError("Native compaction returned no summary")
        with get_session_with_current_tenant() as session:
            persist_summary(
                session,
                chat_history=chat_history,
                text=new_summary,
                token_count=count(new_summary),
                cutoff_id=max(removed_ids),
            )
        return CompressionResult(True, len(removed_ids))
    except Exception as error:
        logger.exception("Native history compaction failed for session %s", session_id)
        return CompressionResult(False, 0, str(error))
