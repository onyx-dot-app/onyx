"""Summarize an older branch prefix while keeping the latest exchange intact.

Summaries attach to the latest user message so sibling answers share the cutoff.
"""

from typing import NamedTuple
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import COMPRESSION_TRIGGER_RATIO
from onyx.configs.constants import MessageType
from onyx.context.messages import count_message_tokens, prepare_model_messages
from onyx.db.agent_transcript import read_agent_transcript
from onyx.db.chat_history import convert_chat_history, create_chat_history_chain
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.tools import get_tools
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import GenerationRequest, Message, SystemMessage, UserMessage
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.compression_prompts import (
    PROGRESSIVE_SUMMARY_SYSTEM_PROMPT_BLOCK,
    PROGRESSIVE_USER_REMINDER,
    SUMMARIZATION_CUTOFF_MARKER,
    SUMMARIZATION_PROMPT,
    USER_REMINDER,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import ChatTraceMetadata, ensure_trace
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The summary prompt asks for long-form output with no token cap, so this call
# outruns the default invoke timeout. A timeout leaves the turn uncompressed.
_SUMMARY_TIMEOUT_S = 180

# Ratio of available context to allocate for recent messages after compression
RECENT_MESSAGES_RATIO = 0.2


class CompressionResult(BaseModel):
    """Result of a compression operation."""

    summary_created: bool
    messages_summarized: int
    error: str | None = None


class CompressionParams(BaseModel):
    """Parameters for compression operation."""

    should_compress: bool
    tokens_for_recent: int = 0


class SummaryContent(NamedTuple):
    """Messages split for summarization."""

    older_messages: list[ChatMessage]
    recent_messages: list[ChatMessage]


def _count_tokens(text: str) -> int:
    return len(get_tokenizer(None, None).encode(text))


def calculate_total_history_tokens(chat_history: list[ChatMessage]) -> int:
    """Count transcript content, with stored token estimates for older rows."""
    total = 0
    for message in chat_history:
        transcript = read_agent_transcript(message)
        if transcript is not None:
            total += sum(
                count_message_tokens(item, _count_tokens)
                for item in transcript.messages
            )
        else:
            total += message.token_count or 0
            total += sum(
                call.tool_call_tokens or 0 for call in message.tool_calls or []
            )
    return total


def get_compression_params(
    max_input_tokens: int,
    current_history_tokens: int,
    reserved_tokens: int,
) -> CompressionParams:
    """
    Calculate compression parameters based on model's context window.

    Args:
        max_input_tokens: The maximum input tokens for the LLM
        current_history_tokens: Current total tokens in chat history
        reserved_tokens: Tokens reserved for system prompt, tools, files, etc.

    Returns:
        CompressionParams indicating whether to compress and token budgets
    """
    available = max_input_tokens - reserved_tokens

    # Check trigger threshold
    trigger_threshold = int(available * COMPRESSION_TRIGGER_RATIO)

    if current_history_tokens <= trigger_threshold:
        return CompressionParams(should_compress=False)

    # Calculate token budget for recent messages as a percentage of current history
    # This ensures we always have messages to summarize when compression triggers
    tokens_for_recent = int(current_history_tokens * RECENT_MESSAGES_RATIO)

    return CompressionParams(
        should_compress=True,
        tokens_for_recent=tokens_for_recent,
    )


def find_summary_for_branch(
    db_session: Session,
    chat_history: list[ChatMessage],
) -> ChatMessage | None:
    """
    Find the most recent summary that applies to the current branch.

    A summary applies if its parent_message_id is in the current chat history,
    meaning it was created on this branch.

    Args:
        db_session: Database session
        chat_history: Branch-aware list of messages

    Returns:
        The applicable summary message, or None if no summary exists for this branch
    """
    if not chat_history:
        return None

    history_ids = {m.id for m in chat_history}
    chat_session_id = chat_history[0].chat_session_id

    # Query all summaries for this session (typically few), then filter in Python.
    # Order by time_sent descending to get the most recent summary first.
    summaries = (
        db_session.query(ChatMessage)
        .filter(
            ChatMessage.chat_session_id == chat_session_id,
            ChatMessage.last_summarized_message_id.isnot(None),
        )
        .order_by(ChatMessage.time_sent.desc())
        .all()
    )
    # Optimization to avoid using IN clause for large histories
    for summary in summaries:
        if summary.parent_message_id in history_ids:
            return summary

    return None


def get_summary_parent_message_id(chat_history: list[ChatMessage]) -> int:
    """Parent for a new summary: the last USER message in the chain.

    Every sibling branch — multi-model answers, regenerations — shares that
    USER message, so the summary applies to whichever answer the user
    continues from. Parenting to the assistant tail would orphan the summary
    for all but that one branch (find_summary_for_branch matches on
    parent_message_id being in the branch's history).
    """
    for msg in reversed(chat_history):
        if msg.message_type == MessageType.USER:
            return msg.id
    logger.warning(
        "No USER message in chat history when parenting summary "
        "(session %s); falling back to chain tail",
        chat_history[-1].chat_session_id,
    )
    return chat_history[-1].id


def get_messages_to_summarize(
    chat_history: list[ChatMessage],
    existing_summary: ChatMessage | None,
    tokens_for_recent: int,
) -> SummaryContent:
    """
    Split messages into those to summarize and those to keep verbatim.

    Args:
        chat_history: Branch-aware list of messages
        existing_summary: Existing summary for this branch (if any)
        tokens_for_recent: Token budget for recent messages to keep

    Returns:
        SummaryContent with older_messages to summarize and recent_messages to keep
    """
    # Filter to messages after the existing summary's cutoff using timestamp
    if existing_summary and existing_summary.last_summarized_message_id:
        cutoff_id = existing_summary.last_summarized_message_id
        last_summarized_msg = next(m for m in chat_history if m.id == cutoff_id)
        messages = [
            m for m in chat_history if m.time_sent > last_summarized_msg.time_sent
        ]
    else:
        messages = list(chat_history)

    # Filter out empty messages
    messages = [
        message
        for message in messages
        if message.message or message.agent_transcript or message.tool_calls
    ]

    if not messages:
        return SummaryContent(older_messages=[], recent_messages=[])

    # Work backwards from most recent, keeping messages until we exceed budget
    recent_messages: list[ChatMessage] = []
    tokens_used = 0

    for msg in reversed(messages):
        # Same per-message cost as the compression trigger (tool-call
        # arguments included) so the verbatim tail respects the budget.
        msg_tokens = calculate_total_history_tokens([msg])
        if tokens_used + msg_tokens > tokens_for_recent and recent_messages:
            break
        recent_messages.insert(0, msg)
        tokens_used += msg_tokens

    # Ensure cutoff is right before a user message by moving any leading
    # non-user messages from recent_messages to older_messages
    while recent_messages and recent_messages[0].message_type != MessageType.USER:
        recent_messages.pop(0)

    if not recent_messages:
        # The verbatim tail had no USER message (e.g. a tool-heavy turn).
        # Rather than summarizing away the latest exchange, keep everything
        # from the last USER message onward; with no USER at all, skip
        # compression entirely (older_messages empty → caller no-ops).
        last_user_idx = next(
            (
                i
                for i in range(len(messages) - 1, -1, -1)
                if messages[i].message_type == MessageType.USER
            ),
            None,
        )
        if last_user_idx is None:
            return SummaryContent(older_messages=[], recent_messages=messages)
        recent_messages = messages[last_user_idx:]

    # Everything else gets summarized
    recent_ids = {m.id for m in recent_messages}
    older_messages = [m for m in messages if m.id not in recent_ids]

    return SummaryContent(
        older_messages=older_messages, recent_messages=recent_messages
    )


def _build_summary_messages(
    messages: list[ChatMessage],
    tool_id_to_name: dict[int, str],
) -> list[Message]:
    """Read canonical history without loading file attachments.

    The shared history reader converts older rows without stored transcripts.
    Standalone legacy tool rows have no call ID and cannot be replayed.
    """
    return convert_chat_history(
        chat_history=[
            message
            for message in messages
            if message.message_type in (MessageType.USER, MessageType.ASSISTANT)
            and (message.message or message.agent_transcript or message.tool_calls)
        ],
        files=[],
        context_image_files=[],
        additional_context=None,
        token_counter=_count_tokens,
        tool_id_to_name_map=tool_id_to_name,
    ).messages


def generate_summary(
    older_messages: list[ChatMessage],
    recent_messages: list[ChatMessage],
    llm: LLM,
    tool_id_to_name: dict[int, str],
    existing_summary: str | None = None,
) -> str:
    """
    Generate a summary using cutoff marker approach.

    The cutoff marker tells the LLM to summarize only older messages,
    while using recent messages as context to inform what's important.

    Messages are sent as separate UserMessage/AssistantMessage objects rather
    than being concatenated into a single message.

    Args:
        older_messages: Messages to compress into summary (before cutoff)
        recent_messages: Messages kept verbatim (after cutoff, for context only)
        llm: LLM to use for summarization
        tool_id_to_name: Mapping of tool IDs to display names
        existing_summary: Previous summary text to incorporate (progressive)

    Returns:
        Summary text
    """
    # Build system prompt
    system_content = SUMMARIZATION_PROMPT
    if existing_summary:
        # Progressive summarization: append existing summary to system prompt
        system_content += PROGRESSIVE_SUMMARY_SYSTEM_PROMPT_BLOCK.format(
            previous_summary=existing_summary
        )
        final_reminder = PROGRESSIVE_USER_REMINDER
    else:
        final_reminder = USER_REMINDER

    older_llm_messages = _build_summary_messages(older_messages, tool_id_to_name)
    recent_llm_messages = _build_summary_messages(recent_messages, tool_id_to_name)

    # Build message list with separate messages
    messages: list[Message] = [
        SystemMessage(content=system_content),
    ]

    # Add older messages (to be summarized)
    messages.extend(older_llm_messages)

    # Add cutoff marker as a user message
    messages.append(UserMessage(content=SUMMARIZATION_CUTOFF_MARKER))

    # Add recent messages (for context only)
    messages.extend(recent_llm_messages)

    # Add final reminder
    messages.append(UserMessage(content=final_reminder))

    response = llm.invoke(
        GenerationRequest(messages=prepare_model_messages(messages, llm.info)),
        context=GenerationContext(flow=LLMFlow.CHAT_HISTORY_SUMMARIZATION),
    )

    content = response.text
    if not (content and content.strip()):
        raise ValueError("LLM returned empty summary")
    return content.strip()


def compress_chat_history(
    chat_history: list[ChatMessage],
    llm: LLM,
    compression_params: CompressionParams,
) -> CompressionResult:
    """Summarize an older branch prefix and persist its cutoff.

    The summary belongs to the latest user message, so sibling answers share it.
    The model request runs without a database session. Legacy rows require
    eager-loaded tool calls; canonical transcripts need no artifact relationships.
    """
    if not chat_history:
        return CompressionResult(summary_created=False, messages_summarized=0)

    chat_session_id = chat_history[0].chat_session_id

    logger.info(
        "Starting compression for session %s, history_len=%s, tokens_for_recent=%s",
        chat_session_id,
        len(chat_history),
        compression_params.tokens_for_recent,
    )

    with ensure_trace(
        "chat_history_compression",
        group_id=str(chat_session_id),
        metadata=ChatTraceMetadata(chat_session_id=str(chat_session_id)).model_dump(),
    ):
        try:
            # Read phase: existing summary + tool name map. Closed before LLM call.
            with get_session_with_current_tenant() as read_session:
                existing_summary = find_summary_for_branch(read_session, chat_history)
                existing_summary_text = (
                    existing_summary.message if existing_summary else None
                )
                all_tools = get_tools(read_session)
                tool_id_to_name: dict[int, str] = {
                    tool.id: tool.name for tool in all_tools
                }

            summary_content = get_messages_to_summarize(
                chat_history,
                existing_summary,
                tokens_for_recent=compression_params.tokens_for_recent,
            )

            if not summary_content.older_messages:
                logger.debug("No messages to summarize, skipping compression")
                return CompressionResult(summary_created=False, messages_summarized=0)

            # LLM call runs with no DB connection held.
            summary_text = generate_summary(
                older_messages=summary_content.older_messages,
                recent_messages=summary_content.recent_messages,
                llm=llm,
                tool_id_to_name=tool_id_to_name,
                existing_summary=existing_summary_text,
            )

            tokenizer = get_tokenizer(None, None)
            summary_token_count = len(tokenizer.encode(summary_text))
            logger.debug(
                "Generated summary (%s tokens): %s...",
                summary_token_count,
                summary_text[:200],
            )

            # Persist phase: fresh short session.
            with get_session_with_current_tenant() as write_session:
                summary_message = ChatMessage(
                    chat_session_id=chat_session_id,
                    message_type=MessageType.ASSISTANT,
                    message=summary_text,
                    token_count=summary_token_count,
                    parent_message_id=get_summary_parent_message_id(chat_history),
                    last_summarized_message_id=summary_content.older_messages[-1].id,
                )
                write_session.add(summary_message)
                write_session.commit()

            logger.info(
                "Compressed %s messages into summary (session_id=%s, summary_tokens=%s)",
                len(summary_content.older_messages),
                chat_session_id,
                summary_token_count,
            )

            return CompressionResult(
                summary_created=True,
                messages_summarized=len(summary_content.older_messages),
            )

        except Exception as e:
            logger.exception(
                "Compression failed for session %s: %s", chat_session_id, e
            )
            return CompressionResult(
                summary_created=False,
                messages_summarized=0,
                error=str(e),
            )


def compress_chat_if_needed(
    chat_session_id: UUID,
    llm: LLM,
    reserved_tokens: int,
    max_input_tokens: int,
) -> None:
    """Check compression once after the request's agent responses are saved."""
    with get_session_with_current_tenant() as session:
        history = create_chat_history_chain(
            chat_session_id=chat_session_id, db_session=session
        )
        summary = find_summary_for_branch(session, history)
        effective_history = history
        summary_tokens = 0
        if summary and summary.last_summarized_message_id:
            effective_history = [
                message
                for message in history
                if message.id > summary.last_summarized_message_id
            ]
            summary_tokens = summary.token_count or 0
        params = get_compression_params(
            max_input_tokens=max_input_tokens,
            current_history_tokens=summary_tokens
            + calculate_total_history_tokens(effective_history),
            reserved_tokens=reserved_tokens,
        )
    if params.should_compress:
        compress_chat_history(chat_history=history, llm=llm, compression_params=params)
