"""Tests for the Postgres tool DB query layer (chat history + search docs).

Covers ownership scoping (a user never sees another user's sessions/messages),
soft-delete, incognito, and subagent-session exclusion, the message-content invariants (empty root node and
non-conversation message types excluded), current-session exclusion, month
grouping, and cited-vs-retrieved SearchDoc lookups.

Everything is scoped by a per-test uuid tag embedded in descriptions/content,
since the tests run against a real shared Postgres.
"""

import re
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, MessageType
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import (
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatSession,
    SearchDoc,
    User,
)
from onyx.db.postgres_tool import (
    count_chat_messages_by_month_for_tool,
    count_chat_messages_for_tool,
    count_chat_sessions_by_month_for_tool,
    count_chat_sessions_for_tool,
    count_search_docs_for_tool,
    query_chat_messages_for_tool,
    query_chat_sessions_for_tool,
    query_search_docs_for_tool,
)
from tests.external_dependency_unit.conftest import MakeTestUser

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _make_session(
    db_session: Session,
    user_id: UUID | None,
    description: str,
    *,
    time_created: datetime | None = None,
    deleted: bool = False,
) -> ChatSession:
    session = ChatSession(
        user_id=user_id,
        description=description,
        deleted=deleted,
    )
    if time_created is not None:
        session.time_created = time_created
    db_session.add(session)
    db_session.flush()
    return session


def _make_message(
    db_session: Session,
    session: ChatSession,
    text: str,
    message_type: MessageType,
    *,
    time_sent: datetime | None = None,
    citations: dict[int, int] | None = None,
) -> ChatMessage:
    message = ChatMessage(
        chat_session_id=session.id,
        message=text,
        token_count=len(text) // 4,
        message_type=message_type,
        citations=citations,
    )
    if time_sent is not None:
        message.time_sent = time_sent
    db_session.add(message)
    db_session.flush()
    return message


def _make_search_doc(db_session: Session, tag: str, idx: int) -> SearchDoc:
    search_doc = SearchDoc(
        document_id=f"pgtool_sd_{idx}_{tag}",
        chunk_ind=0,
        semantic_id=f"Cited Doc {idx} {tag}",
        blurb="blurb",
        boost=0,
        source_type=DocumentSource.WEB,
        hidden=False,
        doc_metadata={},
        score=0.5,
        match_highlights=[],
    )
    db_session.add(search_doc)
    db_session.flush()
    return search_doc


def _texts(messages: list[ChatMessage]) -> set[str]:
    return {m.message for m in messages}


def _descs(sessions: list[ChatSession]) -> set[str]:
    return {s.description or "" for s in sessions}


@dataclass
class ChatEnv:
    tag: str
    user_a: User
    user_b: User
    session_scania: ChatSession  # user_a, ~10 days old
    session_old: ChatSession  # user_a, ~100 days old
    session_deleted: ChatSession  # user_a, soft-deleted
    session_bob: ChatSession  # user_b
    msg_user: ChatMessage
    msg_assistant: ChatMessage  # cites sd_b (citation 1) and sd_a (citation 2)
    msg_old: ChatMessage
    msg_deleted: ChatMessage
    sd_a: SearchDoc
    sd_b: SearchDoc
    sd_c: SearchDoc


@pytest.fixture()
def chat_env(
    db_session: Session, make_test_user: MakeTestUser
) -> Generator[ChatEnv, None, None]:
    tag = uuid4().hex[:8]
    now = datetime.now(timezone.utc)

    user_a = make_test_user(f"pgtool_chat_a_{tag}")
    user_b = make_test_user(f"pgtool_chat_b_{tag}")

    session_scania = _make_session(
        db_session,
        user_a.id,
        f"Scania SharePoint indexing {tag}",
        time_created=now - timedelta(days=10),
    )
    session_old = _make_session(
        db_session,
        user_a.id,
        f"Pricing discussion {tag}",
        time_created=now - timedelta(days=100),
    )
    session_deleted = _make_session(
        db_session,
        user_a.id,
        f"Deleted chat {tag}",
        deleted=True,
    )
    session_bob = _make_session(
        db_session,
        user_b.id,
        f"Bob private chat {tag}",
    )

    sd_a = _make_search_doc(db_session, tag, 1)
    sd_b = _make_search_doc(db_session, tag, 2)
    sd_c = _make_search_doc(db_session, tag, 3)

    # Empty root node — every real session starts with one.
    _make_message(db_session, session_scania, "", MessageType.SYSTEM)
    msg_user = _make_message(
        db_session,
        session_scania,
        f"How fast is Scania sharepoint indexing {tag}",
        MessageType.USER,
        time_sent=now - timedelta(days=10),
    )
    # Citation 1 deliberately points at the higher-id doc (sd_b) to prove
    # results follow citation order, not id order.
    msg_assistant = _make_message(
        db_session,
        session_scania,
        f"Scania indexing throughput answer {tag}",
        MessageType.ASSISTANT,
        time_sent=now - timedelta(days=10) + timedelta(minutes=5),
        citations={1: sd_b.id, 2: sd_a.id},
    )
    for sd in (sd_a, sd_b, sd_c):
        db_session.add(
            ChatMessage__SearchDoc(
                chat_message_id=msg_assistant.id, search_doc_id=sd.id
            )
        )
    # Matches the tag but must be excluded: not a conversation message.
    # (The column is varchar(9), so only SYSTEM/USER/ASSISTANT ever land here.)
    _make_message(
        db_session,
        session_scania,
        f"system note {tag}",
        MessageType.SYSTEM,
    )
    msg_old = _make_message(
        db_session,
        session_old,
        f"Old question about pricing {tag}",
        MessageType.USER,
        time_sent=now - timedelta(days=100),
    )
    msg_deleted = _make_message(
        db_session,
        session_deleted,
        f"Message in deleted session {tag}",
        MessageType.ASSISTANT,
        citations={1: sd_a.id},
    )
    _make_message(
        db_session,
        session_bob,
        f"Bob secret question {tag}",
        MessageType.USER,
    )
    db_session.commit()

    yield ChatEnv(
        tag=tag,
        user_a=user_a,
        user_b=user_b,
        session_scania=session_scania,
        session_old=session_old,
        session_deleted=session_deleted,
        session_bob=session_bob,
        msg_user=msg_user,
        msg_assistant=msg_assistant,
        msg_old=msg_old,
        msg_deleted=msg_deleted,
        sd_a=sd_a,
        sd_b=sd_b,
        sd_c=sd_c,
    )

    # Sessions cascade their messages (ORM), which cascade the linked
    # SearchDocs (ChatMessage.search_docs is "all, delete-orphan");
    # make_test_user deletes the users afterwards.
    for session in (session_scania, session_old, session_deleted, session_bob):
        db_session.delete(session)
    db_session.commit()


def test_chat_session_ownership_and_deleted(
    db_session: Session, chat_env: ChatEnv
) -> None:
    tag = chat_env.tag
    a_sessions = query_chat_sessions_for_tool(
        db_session, chat_env.user_a.id, description_contains=tag, limit=100
    )
    assert _descs(a_sessions) == {
        f"Scania SharePoint indexing {tag}",
        f"Pricing discussion {tag}",
    }

    b_sessions = query_chat_sessions_for_tool(
        db_session, chat_env.user_b.id, description_contains=tag, limit=100
    )
    assert _descs(b_sessions) == {f"Bob private chat {tag}"}


def test_hidden_history_sessions_excluded(
    db_session: Session, chat_env: ChatEnv
) -> None:
    """Incognito chats and subagent child sessions never surface, matching
    the owner's own chat history list."""
    tag = chat_env.tag
    user_id = chat_env.user_a.id
    incognito = _make_session(db_session, user_id, f"Incognito chat {tag}")
    incognito.incognito_record_mode = IncognitoRecordMode.FULL_HISTORY
    child = _make_session(db_session, user_id, f"Research child {tag}")
    child.spawned_by_message_id = chat_env.msg_assistant.id
    for session in (incognito, child):
        _make_message(
            db_session, session, f"hidden history {tag}", MessageType.ASSISTANT
        )
    db_session.commit()

    try:
        sessions = query_chat_sessions_for_tool(
            db_session, user_id, description_contains=tag, limit=100
        )
        assert _descs(sessions) == {
            f"Scania SharePoint indexing {tag}",
            f"Pricing discussion {tag}",
        }
        assert (
            query_chat_messages_for_tool(
                db_session, user_id, content_contains=f"hidden history {tag}"
            )
            == []
        )
    finally:
        for session in (incognito, child):
            db_session.delete(session)
        db_session.commit()


def test_chat_session_filters_and_current_exclusion(
    db_session: Session, chat_env: ChatEnv
) -> None:
    tag = chat_env.tag
    now = datetime.now(timezone.utc)
    user_id = chat_env.user_a.id

    # ILIKE is case-insensitive.
    scania = query_chat_sessions_for_tool(
        db_session, user_id, description_contains=f"sharepoint indexing {tag}"
    )
    assert _descs(scania) == {f"Scania SharePoint indexing {tag}"}

    recent = query_chat_sessions_for_tool(
        db_session,
        user_id,
        description_contains=tag,
        created_after=now - timedelta(days=30),
    )
    assert _descs(recent) == {f"Scania SharePoint indexing {tag}"}

    old = query_chat_sessions_for_tool(
        db_session,
        user_id,
        description_contains=tag,
        created_before=now - timedelta(days=50),
    )
    assert _descs(old) == {f"Pricing discussion {tag}"}

    excluded = query_chat_sessions_for_tool(
        db_session,
        user_id,
        description_contains=tag,
        exclude_chat_session_id=chat_env.session_scania.id,
    )
    assert _descs(excluded) == {f"Pricing discussion {tag}"}


def test_chat_session_count_and_month_grouping(
    db_session: Session, chat_env: ChatEnv
) -> None:
    user_id = chat_env.user_a.id
    count = count_chat_sessions_for_tool(
        db_session, user_id, description_contains=chat_env.tag
    )
    rows = query_chat_sessions_for_tool(
        db_session, user_id, description_contains=chat_env.tag, limit=100
    )
    assert count == len(rows) == 2

    months = count_chat_sessions_by_month_for_tool(
        db_session, user_id, description_contains=chat_env.tag
    )
    # 10d vs 100d ago always land in different months.
    assert len(months) == 2
    assert sum(g.count for g in months) == 2
    assert all(_MONTH_RE.match(g.group) for g in months)
    assert [g.group for g in months] == sorted((g.group for g in months), reverse=True)


def test_chat_message_scoping_and_invariants(
    db_session: Session, chat_env: ChatEnv
) -> None:
    tag = chat_env.tag
    a_messages = query_chat_messages_for_tool(
        db_session, chat_env.user_a.id, content_contains=tag, limit=100
    )
    # The system-note and deleted-session messages match the tag but are
    # excluded; Bob's message is another user's.
    assert _texts(a_messages) == {
        f"How fast is Scania sharepoint indexing {tag}",
        f"Scania indexing throughput answer {tag}",
        f"Old question about pricing {tag}",
    }

    # Within the session, the empty root node and the SYSTEM row are excluded
    # even without a content filter.
    scania_messages = query_chat_messages_for_tool(
        db_session,
        chat_env.user_a.id,
        chat_session_id=chat_env.session_scania.id,
        limit=100,
    )
    assert _texts(scania_messages) == {
        f"How fast is Scania sharepoint indexing {tag}",
        f"Scania indexing throughput answer {tag}",
    }

    b_messages = query_chat_messages_for_tool(
        db_session, chat_env.user_b.id, content_contains=tag, limit=100
    )
    assert _texts(b_messages) == {f"Bob secret question {tag}"}


def test_chat_message_filters_and_ordering(
    db_session: Session, chat_env: ChatEnv
) -> None:
    tag = chat_env.tag
    now = datetime.now(timezone.utc)
    user_id = chat_env.user_a.id

    user_only = query_chat_messages_for_tool(
        db_session,
        user_id,
        content_contains=tag,
        message_type=MessageType.USER,
        limit=100,
    )
    assert _texts(user_only) == {
        f"How fast is Scania sharepoint indexing {tag}",
        f"Old question about pricing {tag}",
    }

    recent = query_chat_messages_for_tool(
        db_session,
        user_id,
        content_contains=tag,
        sent_after=now - timedelta(days=30),
        limit=100,
    )
    assert _texts(recent) == {
        f"How fast is Scania sharepoint indexing {tag}",
        f"Scania indexing throughput answer {tag}",
    }

    excluded = query_chat_messages_for_tool(
        db_session,
        user_id,
        content_contains=tag,
        exclude_chat_session_id=chat_env.session_scania.id,
        limit=100,
    )
    assert _texts(excluded) == {f"Old question about pricing {tag}"}

    ordered = query_chat_messages_for_tool(
        db_session, user_id, content_contains=tag, limit=100
    )
    assert [m.message for m in ordered] == [
        f"Scania indexing throughput answer {tag}",
        f"How fast is Scania sharepoint indexing {tag}",
        f"Old question about pricing {tag}",
    ]


def test_chat_message_count_and_month_grouping(
    db_session: Session, chat_env: ChatEnv
) -> None:
    user_id = chat_env.user_a.id
    count = count_chat_messages_for_tool(
        db_session, user_id, content_contains=chat_env.tag
    )
    assert count == 3

    months = count_chat_messages_by_month_for_tool(
        db_session, user_id, content_contains=chat_env.tag
    )
    assert len(months) == 2
    assert sum(g.count for g in months) == 3
    assert all(_MONTH_RE.match(g.group) for g in months)
    assert [g.group for g in months] == sorted((g.group for g in months), reverse=True)


def test_search_docs_cited_order_and_count(
    db_session: Session, chat_env: ChatEnv
) -> None:
    docs = query_search_docs_for_tool(
        db_session, chat_env.user_a.id, chat_env.msg_assistant.id
    )
    # Citation-number order: citation 1 is sd_b, citation 2 is sd_a.
    assert [d.id for d in docs] == [chat_env.sd_b.id, chat_env.sd_a.id]

    assert (
        count_search_docs_for_tool(
            db_session, chat_env.user_a.id, chat_env.msg_assistant.id
        )
        == 2
    )

    # A message with no citations yields nothing in cited mode.
    assert (
        query_search_docs_for_tool(db_session, chat_env.user_a.id, chat_env.msg_user.id)
        == []
    )
    assert (
        count_search_docs_for_tool(db_session, chat_env.user_a.id, chat_env.msg_user.id)
        == 0
    )


def test_search_docs_retrieved_mode(db_session: Session, chat_env: ChatEnv) -> None:
    docs = query_search_docs_for_tool(
        db_session,
        chat_env.user_a.id,
        chat_env.msg_assistant.id,
        cited_only=False,
    )
    assert {d.id for d in docs} == {
        chat_env.sd_a.id,
        chat_env.sd_b.id,
        chat_env.sd_c.id,
    }
    assert (
        count_search_docs_for_tool(
            db_session,
            chat_env.user_a.id,
            chat_env.msg_assistant.id,
            cited_only=False,
        )
        == 3
    )


def test_search_docs_ownership_scoping(db_session: Session, chat_env: ChatEnv) -> None:
    # Another user's message id yields nothing, not an error.
    assert (
        query_search_docs_for_tool(
            db_session, chat_env.user_b.id, chat_env.msg_assistant.id
        )
        == []
    )
    assert (
        count_search_docs_for_tool(
            db_session, chat_env.user_b.id, chat_env.msg_assistant.id
        )
        == 0
    )

    # Messages in soft-deleted sessions are unreachable even for their owner.
    assert (
        query_search_docs_for_tool(
            db_session, chat_env.user_a.id, chat_env.msg_deleted.id
        )
        == []
    )
