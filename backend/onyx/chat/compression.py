"""
Chat history compression via summarization.

This module handles compressing long chat histories by summarizing older messages
while keeping recent messages verbatim.

Summaries are branch-aware: each summary's parent_message_id points to the last
message when compression triggered, making it part of the tree structure.
"""

from typing import NamedTuple
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.configs.chat_configs import COMPRESSION_TRIGGER_RATIO
from onyx.configs.constants import MessageType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.tools import get_tools
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.compression_prompts import PROGRESSIVE_SUMMARY_SYSTEM_PROMPT_BLOCK
from onyx.prompts.compression_prompts import PROGRESSIVE_USER_REMINDER
from onyx.prompts.compression_prompts import SUMMARIZATION_CUTOFF_MARKER
from onyx.prompts.compression_prompts import SUMMARIZATION_PROMPT
from onyx.prompts.compression_prompts import USER_REMINDER
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import ensure_trace
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Ratio of available context to allocate for recent messages after compression
RECENT_MESSAGES_RATIO = 0.2

# Skip compression when the messages to summarize total fewer tokens than this.
# Each compression is a full LLM round-trip with fixed overhead (system prompt +
# recent-context messages), so summarizing a trivial tail is pure waste.
MIN_TOKENS_TO_COMPRESS = 1000

# Auto-release window for the per-session compression lock. Generous enough for
# a slow summarization LLM call; prevents a crashed holder from blocking the
# session's compression forever.
COMPRESSION_LOCK_TIMEOUT_SECONDS = 300


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
    Find the best summary that applies to the current branch.

    A summary applies if its cutoff (``last_summarized_message_id``) is in the
    current chat history. Every message has exactly one parent, so the path from
    the root to the cutoff is unique — any branch containing the cutoff shares
    the entire summarized prefix, and the summary stays valid even if the tree
    forked after it was created (regenerate, edit, retry, concurrent sends).

    Matching on the summary's ``parent_message_id`` (previous behavior) was
    fragile: ``latest_child_message_id`` is rewritten whenever a sibling is
    created, so any fork after the summary's parent silently orphaned every
    existing summary. Affected sessions then re-summarized their full history
    at the end of every turn and their prompts were never truncated.

    Note: the summarization prompt shows post-cutoff messages "for context
    only", so a summary reused across a fork may carry faint context from a
    sibling branch. Accepted trade-off versus losing compression entirely.

    Args:
        db_session: Database session
        chat_history: Branch-aware list of messages

    Returns:
        The applicable summary with the highest cutoff (most summarization
        progress, ties broken by recency), or None if none applies.
    """
    if not chat_history:
        return None

    history_ids = {m.id for m in chat_history}
    chat_session_id = chat_history[0].chat_session_id

    # Query all summaries for this session (typically few), then filter in
    # Python to avoid an IN clause over large histories. Highest cutoff first
    # so the first applicable summary is the one with the most progress.
    summaries = (
        db_session.query(ChatMessage)
        .filter(
            ChatMessage.chat_session_id == chat_session_id,
            ChatMessage.last_summarized_message_id.isnot(None),
        )
        .order_by(
            ChatMessage.last_summarized_message_id.desc(),
            ChatMessage.time_sent.desc(),
        )
        .all()
    )
    for summary in summaries:
        if summary.last_summarized_message_id in history_ids:
            return summary

    return None


def calculate_effective_history_tokens(
    chat_history: list[ChatMessage],
    existing_summary: ChatMessage | None,
) -> int:
    """
    Token count of what the next prompt will actually contain: the applicable
    summary (if any) plus the messages after its cutoff.

    Using the raw chain total instead (previous behavior) meant that once a
    session ever crossed the compression threshold, compression re-triggered at
    the end of every subsequent turn — already-summarized messages still count
    toward the raw total even though they never reach the prompt.
    """
    if not existing_summary or not existing_summary.last_summarized_message_id:
        return calculate_total_history_tokens(chat_history)

    cutoff_id = existing_summary.last_summarized_message_id
    post_cutoff_tokens = sum(
        m.token_count or 0 for m in chat_history if m.id > cutoff_id
    )
    return post_cutoff_tokens + (existing_summary.token_count or 0)


def trim_history_to_token_budget(
    chat_history: list[ChatMessage],
    token_budget: int,
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """
    Keep the longest suffix of ``chat_history`` that fits in ``token_budget``,
    aligned to start at a USER message (mirroring the compression cutoff rule).
    The most recent message is always kept, even if over budget.

    This is the emergency fallback for when no summary applies to the branch:
    it bounds prompt size instead of shipping the entire raw history to the LLM
    on every agent-loop iteration.

    Returns:
        (kept_messages, dropped_messages) — both in original order.
    """
    kept: list[ChatMessage] = []
    tokens_used = 0

    for msg in reversed(chat_history):
        msg_tokens = msg.token_count or 0
        if tokens_used + msg_tokens > token_budget and kept:
            break
        kept.insert(0, msg)
        tokens_used += msg_tokens

    # Align the cut to right before a user message so the LLM never sees a
    # conversation that opens mid-exchange (e.g. with a dangling tool response).
    while kept and kept[0].message_type != MessageType.USER:
        kept.pop(0)

    if not kept:
        kept = chat_history[-1:]

    kept_ids = {m.id for m in kept}
    dropped = [m for m in chat_history if m.id not in kept_ids]
    return kept, dropped


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

    # Ensure cutoff is right before a user message by moving any leading
    # non-user messages from recent_messages to older_messages
    while recent_messages and recent_messages[0].message_type != MessageType.USER:
        recent_messages.pop(0)

    # Everything else gets summarized
    recent_ids = {m.id for m in recent_messages}
    older_messages = [m for m in messages if m.id not in recent_ids]

    return SummaryContent(
        older_messages=older_messages, recent_messages=recent_messages
    )


def _build_llm_messages_for_summarization(
    messages: list[ChatMessage],
    tool_id_to_name: dict[int, str],
) -> list[UserMessage | AssistantMessage]:
    """Convert ChatMessage objects to LLM message format for summarization.

    This is intentionally different from translate_history_to_llm_format in llm_step.py:
    - Compacts tool calls to "[Used tools: tool1, tool2]" to save tokens in summaries
    - Skips TOOL_CALL_RESPONSE messages entirely (tool usage captured in assistant message)
    - No image/multimodal handling (summaries are text-only)
    - No caching or LLMConfig-specific behavior needed
    """
    result: list[UserMessage | AssistantMessage] = []

    for msg in messages:
        # Skip empty messages
        if not msg.message:
            continue

        # Handle assistant messages with tool calls compactly
        if msg.message_type == MessageType.ASSISTANT:
            if msg.tool_calls:
                tool_names = [
                    tool_id_to_name.get(tc.tool_id, "unknown") for tc in msg.tool_calls
                ]
                result.append(
                    AssistantMessage(content=f"[Used tools: {', '.join(tool_names)}]")
                )
            else:
                result.append(AssistantMessage(content=msg.message))
            continue

        # Skip tool call response messages - tool calls are captured above via assistant messages
        if msg.message_type == MessageType.TOOL_CALL_RESPONSE:
            continue

        # Handle user messages
        if msg.message_type == MessageType.USER:
            result.append(UserMessage(content=msg.message))

    return result


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

    # Convert messages to LLM format (using compression-specific conversion)
    older_llm_messages = _build_llm_messages_for_summarization(
        older_messages, tool_id_to_name
    )
    recent_llm_messages = _build_llm_messages_for_summarization(
        recent_messages, tool_id_to_name
    )

    # Build message list with separate messages
    input_messages: list[ChatCompletionMessage] = [
        SystemMessage(content=system_content),
    ]

    # Add older messages (to be summarized)
    input_messages.extend(older_llm_messages)

    # Add cutoff marker as a user message
    input_messages.append(UserMessage(content=SUMMARIZATION_CUTOFF_MARKER))

    # Add recent messages (for context only)
    input_messages.extend(recent_llm_messages)

    # Add final reminder
    input_messages.append(UserMessage(content=final_reminder))

    with llm_generation_span(
        llm=llm,
        flow=LLMFlow.CHAT_HISTORY_SUMMARIZATION,
        input_messages=input_messages,
    ) as span_generation:
        response = llm.invoke(input_messages)
        record_llm_response(span_generation, response)

    content = response.choice.message.content
    if not (content and content.strip()):
        raise ValueError("LLM returned empty summary")
    return content.strip()


def compress_chat_history(
    chat_history: list[ChatMessage],
    llm: LLM,
    compression_params: CompressionParams,
) -> CompressionResult:
    """
    Main compression function. Creates a summary ChatMessage.

    The summary message's parent_message_id points to the last message in
    chat_history, making it branch-aware via the tree structure.

    Note: This takes the entire chat history as input, splits it into older
    messages (to summarize) and recent messages (kept verbatim within the
    token budget), generates a summary of the older part, and persists the
    new summary message with its parent set to the last message in history.

    Past summary is taken into context (progressive summarization): we find
    at most one existing summary for this branch. If present, only messages
    after that summary's last_summarized_message_id are considered; the
    existing summary text is passed into the LLM so the new summary
    incorporates it instead of summarizing from scratch.

    Sessions are short-lived: one for the read phase (existing summary +
    tool name map), the LLM call runs with no session held, and a fresh
    session is opened to persist the summary. ``chat_history`` items may
    be detached, but callers must have eager-loaded the ``tool_calls``
    relationship (e.g. via ``create_chat_history_chain`` with the default
    ``prefetch_top_two_level_tool_calls=True``); ``_build_llm_messages_for_summarization``
    walks ``msg.tool_calls`` and would raise ``DetachedInstanceError`` if
    the relationship were lazy on a detached instance.

    For more details, see the COMPRESSION.md file.

    Args:
        chat_history: Branch-aware list of messages
        llm: LLM to use for summarization
        compression_params: Parameters from get_compression_params

    Returns:
        CompressionResult indicating success/failure
    """
    if not chat_history:
        return CompressionResult(summary_created=False, messages_summarized=0)

    chat_session_id = chat_history[0].chat_session_id

    # Only one compression per session at a time. Concurrent turns on the same
    # session (rapid-fire sends, regenerates, retries) would otherwise each run
    # their own expensive summarization LLM call over largely the same messages.
    # Compression is best-effort: cache backend trouble must never break the
    # turn, so on lock infrastructure errors we proceed without dedup instead
    # of propagating (or silently dropping compression).
    lock: CacheLock | None = None
    try:
        lock = get_cache_backend().lock(
            f"chat_compression_lock:{chat_session_id}",
            timeout=COMPRESSION_LOCK_TIMEOUT_SECONDS,
        )
        if not lock.acquire(blocking=False):
            logger.info(
                "Skipping compression for session %s: another compression is in flight",
                chat_session_id,
            )
            return CompressionResult(summary_created=False, messages_summarized=0)
    except Exception:
        logger.warning(
            "Compression lock unavailable for session %s; "
            "proceeding without concurrency dedup",
            chat_session_id,
            exc_info=True,
        )
        lock = None

    try:
        return _compress_chat_history_locked(
            chat_history=chat_history,
            llm=llm,
            compression_params=compression_params,
            chat_session_id=chat_session_id,
        )
    finally:
        if lock is not None:
            try:
                # The lock auto-expires after COMPRESSION_LOCK_TIMEOUT_SECONDS;
                # if compression outlived it, another holder may own it now —
                # releasing would raise (e.g. redis LockNotOwnedError).
                if lock.owned():
                    lock.release()
            except Exception:
                logger.warning(
                    "Failed to release compression lock for session %s",
                    chat_session_id,
                )


def _compress_chat_history_locked(
    chat_history: list[ChatMessage],
    llm: LLM,
    compression_params: CompressionParams,
    chat_session_id: UUID,
) -> CompressionResult:
    """Body of compress_chat_history; caller holds the per-session lock."""
    logger.info(
        "Starting compression for session %s, history_len=%s, tokens_for_recent=%s",
        chat_session_id,
        len(chat_history),
        compression_params.tokens_for_recent,
    )

    with ensure_trace(
        "chat_history_compression",
        group_id=str(chat_session_id),
        metadata={
            "tenant_id": get_current_tenant_id(),
            "chat_session_id": str(chat_session_id),
        },
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

            # Not worth a full LLM round-trip to summarize a trivial tail. Also
            # serves as the double-check after acquiring the lock: if a
            # concurrent compression just finished, the re-found summary leaves
            # only the newest messages here.
            older_tokens = calculate_total_history_tokens(
                summary_content.older_messages
            )
            if older_tokens < MIN_TOKENS_TO_COMPRESS:
                logger.info(
                    "Skipping compression for session %s: only %s tokens to "
                    "summarize (min %s)",
                    chat_session_id,
                    older_tokens,
                    MIN_TOKENS_TO_COMPRESS,
                )
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
                    parent_message_id=chat_history[-1].id,
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
