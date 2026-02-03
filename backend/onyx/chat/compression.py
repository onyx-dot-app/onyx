"""
Chat history compression via summarization.

This module handles compressing long chat histories by summarizing older messages
while keeping recent messages verbatim.

Summaries are branch-aware: each summary's parent_message_id points to the last
message when compression triggered, making it part of the tree structure.
"""

from typing import NamedTuple

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import COMPRESSION_TRIGGER_RATIO
from onyx.configs.constants import MessageType
from onyx.db.models import ChatMessage
from onyx.llm.interfaces import LLM
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.compression_prompts import PROGRESSIVE_SUMMARY_PROMPT
from onyx.prompts.compression_prompts import PROGRESSIVE_USER_REMINDER
from onyx.prompts.compression_prompts import SUMMARIZATION_CUTOFF_MARKER
from onyx.prompts.compression_prompts import SUMMARIZATION_PROMPT
from onyx.prompts.compression_prompts import USER_FINAL_REMINDER
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Ratio of available context to allocate for recent messages after compression
RECENT_MESSAGES_RATIO = 0.25


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


def calculate_total_history_tokens(chat_history: list[ChatMessage]) -> int:
    """
    Calculate the total token count for the given chat history.

    Args:
        chat_history: Branch-aware list of messages

    Returns:
        Total token count for the history
    """
    return sum(m.token_count or 0 for m in chat_history)


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
    messages = [m for m in messages if m.message]

    if not messages:
        return SummaryContent(older_messages=[], recent_messages=[])

    # Work backwards from most recent, keeping messages until we exceed budget
    recent_messages: list[ChatMessage] = []
    tokens_used = 0

    for msg in reversed(messages):
        msg_tokens = msg.token_count or 0
        if tokens_used + msg_tokens > tokens_for_recent and recent_messages:
            break
        recent_messages.insert(0, msg)
        tokens_used += msg_tokens

    # Everything else gets summarized
    recent_ids = {m.id for m in recent_messages}
    older_messages = [m for m in messages if m.id not in recent_ids]

    return SummaryContent(
        older_messages=older_messages, recent_messages=recent_messages
    )


def format_messages_for_summary(
    messages: list[ChatMessage],
    tool_id_to_name: dict[int, str],
) -> str:
    """Format messages into a string for the summarization prompt.

    Tool call messages are formatted compactly to save tokens.
    """
    formatted = []
    for msg in messages:
        # Format assistant messages with tool calls compactly
        if msg.message_type == MessageType.ASSISTANT and msg.tool_calls:
            tool_names = [
                tool_id_to_name.get(tc.tool_id, "unknown") for tc in msg.tool_calls
            ]
            formatted.append(f"[assistant used tools: {', '.join(tool_names)}]")
            continue

        # Skip tool call response messages - tool calls are captured above via assistant messages
        if msg.message_type == MessageType.TOOL_CALL_RESPONSE:
            continue

        role = msg.message_type.value
        formatted.append(f"[{role}]: {msg.message}")
    return "\n\n".join(formatted)


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

    Args:
        older_messages: Messages to compress into summary (before cutoff)
        recent_messages: Messages kept verbatim (after cutoff, for context only)
        llm: LLM to use for summarization
        tool_id_to_name: Mapping of tool IDs to display names
        existing_summary: Previous summary text to incorporate (progressive)

    Returns:
        Summary text
    """
    older_messages_str = format_messages_for_summary(older_messages, tool_id_to_name)
    recent_messages_str = format_messages_for_summary(recent_messages, tool_id_to_name)

    # Build user prompt with cutoff marker
    if existing_summary:
        # Progressive summarization: include existing summary
        user_prompt = PROGRESSIVE_SUMMARY_PROMPT.format(
            existing_summary=existing_summary
        )
        user_prompt += f"\n\n{older_messages_str}"
        final_reminder = PROGRESSIVE_USER_REMINDER
    else:
        # Initial summarization
        user_prompt = older_messages_str
        final_reminder = USER_FINAL_REMINDER

    # Add cutoff marker and recent messages as context
    user_prompt += f"\n\n{SUMMARIZATION_CUTOFF_MARKER}"
    if recent_messages_str:
        user_prompt += f"\n\n{recent_messages_str}"

    # Add final reminder
    user_prompt += f"\n\n{final_reminder}"

    response = llm.invoke(
        [
            SystemMessage(content=SUMMARIZATION_PROMPT),
            UserMessage(content=user_prompt),
        ]
    )
    return response.choice.message.content or ""


def compress_chat_history(
    db_session: Session,
    chat_history: list[ChatMessage],
    llm: LLM,
    compression_params: CompressionParams,
    tool_id_to_name: dict[int, str],
) -> CompressionResult:
    """
    Main compression function. Creates a summary ChatMessage.

    The summary message's parent_message_id points to the last message in
    chat_history, making it branch-aware via the tree structure.

    Args:
        db_session: Database session
        chat_history: Branch-aware list of messages
        llm: LLM to use for summarization
        compression_params: Parameters from get_compression_params
        tool_id_to_name: Mapping of tool IDs to display names

    Returns:
        CompressionResult indicating success/failure
    """
    if not chat_history:
        return CompressionResult(summary_created=False, messages_summarized=0)

    logger.info(
        f"Starting compression for session {chat_history[0].chat_session_id}, "
        f"history_len={len(chat_history)}, tokens_for_recent={compression_params.tokens_for_recent}"
    )

    try:
        # Find existing summary for this branch
        existing_summary = find_summary_for_branch(db_session, chat_history)

        # Get messages to summarize
        summary_content = get_messages_to_summarize(
            chat_history,
            existing_summary,
            tokens_for_recent=compression_params.tokens_for_recent,
        )

        if not summary_content.older_messages:
            logger.debug("No messages to summarize, skipping compression")
            return CompressionResult(summary_created=False, messages_summarized=0)

        # Generate summary (incorporate existing summary if present)
        existing_summary_text = existing_summary.message if existing_summary else None
        summary_text = generate_summary(
            older_messages=summary_content.older_messages,
            recent_messages=summary_content.recent_messages,
            llm=llm,
            tool_id_to_name=tool_id_to_name,
            existing_summary=existing_summary_text,
        )

        # Calculate token count for the summary
        tokenizer = get_tokenizer(None, None)
        summary_token_count = len(tokenizer.encode(summary_text))
        logger.debug(
            f"Generated summary ({summary_token_count} tokens): {summary_text[:200]}..."
        )

        # Create new summary as a ChatMessage
        # Parent is the last message in history - this makes the summary branch-aware
        summary_message = ChatMessage(
            chat_session_id=chat_history[0].chat_session_id,
            message_type=MessageType.ASSISTANT,
            message=summary_text,
            token_count=summary_token_count,
            parent_message_id=chat_history[-1].id,
            last_summarized_message_id=summary_content.older_messages[-1].id,
        )
        db_session.add(summary_message)
        db_session.commit()

        logger.info(
            f"Compressed {len(summary_content.older_messages)} messages into summary "
            f"(session_id={chat_history[0].chat_session_id}, "
            f"summary_tokens={summary_token_count})"
        )

        return CompressionResult(
            summary_created=True,
            messages_summarized=len(summary_content.older_messages),
        )

    except Exception as e:
        logger.exception(
            f"Compression failed for session {chat_history[0].chat_session_id}: {e}"
        )
        db_session.rollback()
        return CompressionResult(
            summary_created=False,
            messages_summarized=0,
            error=str(e),
        )
