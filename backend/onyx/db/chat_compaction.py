"""Persist branch summaries produced by native agent compaction."""

from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.models import ChatMessage
from onyx.utils.logger import setup_logger

logger = setup_logger()


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


def persist_summary(
    db_session: Session,
    *,
    chat_history: list[ChatMessage],
    text: str,
    token_count: int,
    cutoff_id: int,
) -> None:
    db_session.add(
        ChatMessage(
            chat_session_id=chat_history[0].chat_session_id,
            message_type=MessageType.ASSISTANT,
            message=text,
            token_count=token_count,
            parent_message_id=get_summary_parent_message_id(chat_history),
            last_summarized_message_id=cutoff_id,
        )
    )
    db_session.commit()
