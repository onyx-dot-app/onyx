"""
Chat history compression via summarization.

This module handles compressing long chat histories by summarizing older messages
while keeping recent messages verbatim.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import COMPRESSION_TRIGGER_RATIO
from onyx.configs.constants import MessageType
from onyx.db.chat import get_or_create_root_message
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.llm.interfaces import LLM
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Tokens reserved for system prompt, tool definitions, current user message, and safety margin
RESERVED_CONTEXT_TOKENS = 3000

# Ratio of available context to allocate for recent messages after compression
RECENT_MESSAGES_RATIO = 0.25

SUMMARY_SYSTEM_PROMPT = """You are a conversation summarizer. Your task is to create \
a concise but comprehensive summary of the conversation history provided.

Your summary MUST preserve:
1. Key decisions and conclusions reached
2. Important user requirements and preferences stated
3. Technical context (files discussed, errors encountered, solutions proposed)
4. Any ongoing tasks or unresolved questions
5. Relevant code snippets or commands (abbreviated if long)

Format your summary as:

## Context
[Brief overview of what this conversation is about]

## Key Points
- [Important point 1]
- [Important point 2]

## Decisions Made
- [Decision 1]
- [Decision 2]

## Current State
[Where the conversation left off, any pending items]

Be concise but thorough. The summary will be used to maintain context in a long conversation."""


@dataclass
class CompressionResult:
    """Result of a compression operation."""

    summary_created: bool
    messages_summarized: int
    error: str | None = None


@dataclass
class CompressionParams:
    """Parameters for compression operation."""

    should_compress: bool
    tokens_for_recent: int = 0


def calculate_total_history_tokens(
    db_session: Session,
    chat_session_id: UUID,
) -> int:
    """
    Calculate the total token count for a chat session.

    This uses an aggregate query (SUM) which is fast and doesn't load message content.

    Args:
        db_session: Database session
        chat_session_id: The chat session ID

    Returns:
        Total token count for all messages in the session
    """
    result = (
        db_session.query(func.sum(ChatMessage.token_count))
        .filter(ChatMessage.chat_session_id == chat_session_id)
        .scalar()
    )

    return result or 0


def get_compression_params(
    llm: LLM,
    current_history_tokens: int,
) -> CompressionParams:
    """
    Calculate compression parameters based on model's context window.

    Args:
        llm: The LLM instance (used to get max_input_tokens)
        current_history_tokens: Current total tokens in chat history

    Returns:
        CompressionParams indicating whether to compress and token budgets
    """
    max_context = llm.config.max_input_tokens
    available = max_context - RESERVED_CONTEXT_TOKENS

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


def get_messages_to_summarize(
    db_session: Session,
    chat_session: ChatSession,
    tokens_for_recent: int,
) -> tuple[list[ChatMessage], list[ChatMessage], ChatMessage | None]:
    """
    Split messages into those to summarize and those to keep verbatim.

    Args:
        db_session: Database session
        chat_session: The chat session to process
        tokens_for_recent: Token budget for recent messages to keep

    Returns:
        Tuple of (messages_to_summarize, messages_to_keep, existing_summary_message)
    """
    from onyx.db.chat import get_chat_messages_by_session

    all_messages = get_chat_messages_by_session(
        chat_session_id=chat_session.id,
        user_id=None,
        db_session=db_session,
        skip_permission_check=True,
        prefetch_top_two_level_tool_calls=False,
    )

    # Get existing summary if present
    existing_summary: ChatMessage | None = None
    cutoff_id: int | None = None
    if chat_session.summary_message_id is not None:
        existing_summary = db_session.get(ChatMessage, chat_session.summary_message_id)
        if existing_summary:
            cutoff_id = existing_summary.last_summarized_message_id

    # Filter to messages after the cutoff (exclude summary message itself)
    if cutoff_id is not None:
        all_messages = [
            m
            for m in all_messages
            if m.id > cutoff_id and m.id != chat_session.summary_message_id
        ]
    else:
        all_messages = [
            m for m in all_messages if m.id != chat_session.summary_message_id
        ]

    # Filter out root message (empty message with no parent)
    all_messages = [m for m in all_messages if m.message]

    if not all_messages:
        return [], [], existing_summary

    # Work backwards from most recent, keeping messages until we exceed budget
    to_keep: list[ChatMessage] = []
    tokens_used = 0

    for msg in reversed(all_messages):
        msg_tokens = msg.token_count or 0
        if tokens_used + msg_tokens > tokens_for_recent and to_keep:
            break
        to_keep.insert(0, msg)
        tokens_used += msg_tokens

    # Everything else gets summarized
    keep_ids = {m.id for m in to_keep}
    to_summarize = [m for m in all_messages if m.id not in keep_ids]

    return to_summarize, to_keep, existing_summary


def format_messages_for_summary(messages: list[ChatMessage]) -> str:
    """Format messages into a string for the summarization prompt."""
    formatted = []
    for msg in messages:
        role = msg.message_type.value
        formatted.append(f"[{role}]: {msg.message}")
    return "\n\n".join(formatted)


def generate_summary(
    messages: list[ChatMessage],
    llm: LLM,
    existing_summary: str | None = None,
) -> str:
    """
    Generate a summary of the provided messages.

    If existing_summary provided, incorporate it (progressive summarization).

    Args:
        messages: Messages to summarize
        llm: LLM to use for summarization
        existing_summary: Previous summary text to incorporate

    Returns:
        Summary text
    """
    messages_text = format_messages_for_summary(messages)

    if existing_summary:
        user_prompt = f"""The conversation has a previous summary:

{existing_summary}

Now, incorporate the following new messages into an updated summary:

{messages_text}

Create a unified summary that combines both the previous context and new information."""
    else:
        user_prompt = f"Please summarize the following conversation:\n\n{messages_text}"

    response = llm.invoke(
        [
            SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
            UserMessage(content=user_prompt),
        ]
    )
    return response.choice.message.content or ""


def compress_chat_history(
    db_session: Session,
    chat_session: ChatSession,
    llm: LLM,
    compression_params: CompressionParams,
) -> CompressionResult:
    """
    Main compression function. Creates a summary ChatMessage.

    Args:
        db_session: Database session
        chat_session: The chat session to compress
        llm: LLM to use for summarization
        compression_params: Parameters from get_compression_params

    Returns:
        CompressionResult indicating success/failure
    """
    try:
        # Get messages to summarize and existing summary
        to_summarize, to_keep, existing_summary = get_messages_to_summarize(
            db_session,
            chat_session,
            tokens_for_recent=compression_params.tokens_for_recent,
        )

        if not to_summarize:
            return CompressionResult(summary_created=False, messages_summarized=0)

        # Generate summary (incorporate existing summary if present)
        existing_summary_text = existing_summary.message if existing_summary else None
        summary_text = generate_summary(
            to_summarize,
            llm,
            existing_summary=existing_summary_text,
        )

        # Calculate token count for the summary
        tokenizer = get_tokenizer(None, None)
        summary_token_count = len(tokenizer.encode(summary_text))

        # Get the root message to use as parent for the summary
        root_message = get_or_create_root_message(
            chat_session_id=chat_session.id,
            db_session=db_session,
        )

        # Create new summary as a ChatMessage
        summary_message = ChatMessage(
            chat_session_id=chat_session.id,
            message_type=MessageType.ASSISTANT,
            message=summary_text,
            token_count=summary_token_count,
            parent_message_id=root_message.id,  # Child of root to avoid conflicts
            last_summarized_message_id=to_summarize[-1].id,
        )
        db_session.add(summary_message)
        db_session.flush()  # Get the ID

        # Update chat session to point to new summary
        chat_session.summary_message_id = summary_message.id

        db_session.commit()

        logger.info(
            f"Compressed {len(to_summarize)} messages into summary "
            f"(session_id={chat_session.id}, summary_tokens={summary_token_count})"
        )

        return CompressionResult(
            summary_created=True,
            messages_summarized=len(to_summarize),
        )

    except Exception as e:
        logger.exception(f"Compression failed for session {chat_session.id}: {e}")
        db_session.rollback()
        return CompressionResult(
            summary_created=False,
            messages_summarized=0,
            error=str(e),
        )


def get_compressed_history(
    db_session: Session,
    chat_session: ChatSession,
) -> tuple[ChatMessage | None, list[ChatMessage]]:
    """
    Get the compressed history for a chat session.

    Args:
        db_session: Database session
        chat_session: The chat session

    Returns:
        Tuple of (summary_message, recent_messages) - summary may be None if no compression done
    """
    from onyx.db.chat import get_chat_messages_by_session

    # Get summary message if exists
    summary_message: ChatMessage | None = None
    cutoff_id: int | None = None
    if chat_session.summary_message_id is not None:
        summary_message = db_session.get(ChatMessage, chat_session.summary_message_id)
        if summary_message:
            cutoff_id = summary_message.last_summarized_message_id

    # Get all messages
    all_messages = get_chat_messages_by_session(
        chat_session_id=chat_session.id,
        user_id=None,
        db_session=db_session,
        skip_permission_check=True,
        prefetch_top_two_level_tool_calls=False,
    )

    # Filter to messages after cutoff, excluding the summary message itself
    if cutoff_id is not None:
        recent_messages = [
            m
            for m in all_messages
            if m.id > cutoff_id and m.id != chat_session.summary_message_id
        ]
    else:
        recent_messages = [
            m for m in all_messages if m.id != chat_session.summary_message_id
        ]

    return summary_message, recent_messages
