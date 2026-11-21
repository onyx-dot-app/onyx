"""Tests for PostgresTool.run(): LLM-arg validation, per-table dispatch to the
DB query layer, and result formatting (counts, grouped counts, rows with
ids/links, truncation notes).

The fine-grained ACL/ownership behavior is covered by the DB-layer tests
(test_postgres_tool_queries.py / test_postgres_tool_chat_queries.py); here we
exercise the tool end-to-end minus the LLM and HTTP layers, with a real
Postgres.
"""

from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy.orm import Session

from onyx.agents.tools import ToolInvocation
from onyx.configs.constants import (
    ANONYMOUS_USER_EMAIL,
    ANONYMOUS_USER_UUID,
    DocumentSource,
    MessageType,
)
from onyx.context.search.models import SearchDocsResponse
from onyx.db.models import (
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatSession,
    ConnectorCredentialPair,
    DocumentByConnectorCredentialPair,
    SearchDoc,
    User,
)
from onyx.db.models import Document as DbDocument
from onyx.db.postgres_tool_models import DocumentScope
from onyx.kg.models import KGStage
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.postgres.postgres_tool import (
    PostgresTool,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


def _invoke_in_context(
    tool: PostgresTool,
    context: ToolContext,
    call_index: int,
    llm_kwargs: dict[str, JsonValue],
) -> ToolResult:
    result = tool.run(
        ToolInvocation(
            call_id="call",
            arguments=llm_kwargs,
            call_index=call_index,
            cancellation=CancellationSignal(),
            update=lambda _: None,
        ),
        context,
    )
    assert isinstance(result, ToolResult)
    return result


def _invoke(tool: PostgresTool, **llm_kwargs: JsonValue) -> ToolResult:
    return _invoke_in_context(tool, ToolContext(), 0, llm_kwargs)


def _run(tool: PostgresTool, **llm_kwargs: JsonValue) -> str:
    result = _invoke(tool, **llm_kwargs)
    assert not result.is_error, result.content
    return result.content


def _run_error(tool: PostgresTool, **llm_kwargs: JsonValue) -> str:
    """Rejected calls come back to the model as an error result."""
    result = _invoke(tool, **llm_kwargs)
    assert result.is_error
    return result.content


def _tool_excluding(env: "ToolEnv", chat_session_id: UUID) -> PostgresTool:
    return PostgresTool(
        user=env.user,
        current_chat_session_id=chat_session_id,
        scope=DocumentScope(),
    )


@dataclass
class ToolEnv:
    tag: str
    tool: PostgresTool
    user: User
    cc_pair: ConnectorCredentialPair
    session_current: ChatSession
    session_other: ChatSession
    msg_cited: ChatMessage  # in session_other; cites sd_a and sd_b, retrieved sd_c too
    sd_a: SearchDoc
    sd_b: SearchDoc
    sd_c: SearchDoc


@pytest.fixture()
def tool_env(
    db_session: Session, make_test_user: MakeTestUser
) -> Generator[ToolEnv, None, None]:
    tag = uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    user = make_test_user(f"pgtool_run_{tag}")

    cc_pair = make_cc_pair(db_session, source=DocumentSource.WEB)
    for idx, days_ago in enumerate([1, 40]):
        doc_id = f"pgtool_run_doc_{idx}_{tag}"
        db_session.add(
            DbDocument(
                id=doc_id,
                semantic_id=f"Runbook {idx} {tag}",
                link=f"https://example.com/{doc_id}",
                primary_owners=[f"owner_{tag}@example.com"],
                doc_updated_at=now - timedelta(days=days_ago),
                kg_stage=KGStage.NOT_STARTED,
            )
        )
        db_session.flush()
        db_session.add(
            DocumentByConnectorCredentialPair(
                id=doc_id,
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
                has_been_indexed=True,
            )
        )

    session_current = ChatSession(
        user_id=user.id, description=f"Current conversation {tag}"
    )
    session_other = ChatSession(
        user_id=user.id, description=f"Past scania conversation {tag}"
    )
    db_session.add_all([session_current, session_other])
    db_session.flush()

    search_docs = []
    for idx in range(3):
        sd = SearchDoc(
            document_id=f"pgtool_run_sd_{idx}_{tag}",
            chunk_ind=0,
            semantic_id=f"Source Doc {idx} {tag}",
            blurb="blurb",
            boost=0,
            source_type=DocumentSource.WEB,
            hidden=False,
            doc_metadata={},
            score=0.5,
            match_highlights=[],
        )
        db_session.add(sd)
        search_docs.append(sd)
    db_session.flush()
    sd_a, sd_b, sd_c = search_docs

    db_session.add(
        ChatMessage(
            chat_session_id=session_current.id,
            message=f"the in-flight scania question {tag}",
            token_count=10,
            message_type=MessageType.USER,
        )
    )
    msg_cited = ChatMessage(
        chat_session_id=session_other.id,
        message=f"scania answer with sources {tag}",
        token_count=10,
        message_type=MessageType.ASSISTANT,
        citations={1: sd_a.id, 2: sd_b.id},
    )
    db_session.add(msg_cited)
    db_session.flush()
    for sd in search_docs:
        db_session.add(
            ChatMessage__SearchDoc(chat_message_id=msg_cited.id, search_doc_id=sd.id)
        )
    db_session.commit()

    tool = PostgresTool(user=user, current_chat_session_id=None, scope=DocumentScope())

    yield ToolEnv(
        tag=tag,
        tool=tool,
        user=user,
        cc_pair=cc_pair,
        session_current=session_current,
        session_other=session_other,
        msg_cited=msg_cited,
        sd_a=sd_a,
        sd_b=sd_b,
        sd_c=sd_c,
    )

    # A failed statement leaves the session's transaction aborted.
    db_session.rollback()
    cleanup_cc_pair(db_session, cc_pair)
    for session in (session_current, session_other):
        db_session.delete(session)
    db_session.commit()


def test_validation_errors(tool_env: ToolEnv) -> None:
    tool = tool_env.tool

    message = _run_error(tool)
    assert "'table' is required" in message

    message = _run_error(tool, table="user")
    assert "must be one of" in message

    message = _run_error(tool, table="chat_session", title_contains="x")
    assert "do not apply to table 'chat_session'" in message
    assert "description_contains" in message

    message = _run_error(tool, table="document", group_by="source")
    assert "requires count=true" in message

    message = _run_error(tool, table="chat_session", count=True, group_by="owner")
    assert "not valid for table 'chat_session'" in message

    message = _run_error(tool, table="document", updated_after="last tuesday")
    assert "not a valid ISO date" in message

    message = _run_error(tool, table="document", source_type="carrier_pigeon")
    assert "Invalid source_type" in message

    message = _run_error(tool, table="search_doc")
    assert "requires 'chat_message_id'" in message

    message = _run_error(tool, table="chat_message", message_type="system")
    assert "must be 'user' or 'assistant'" in message

    message = _run_error(tool, table="document", limit=0)
    assert "'limit' must be at least 1" in message

    message = _run_error(tool, table="document", frobnicate=1)
    assert "Unknown field" in message


def test_anonymous_user_cannot_query_chat_history() -> None:
    """All anonymous visitors share one user row, so chat history is off-limits."""
    anonymous = User(id=UUID(ANONYMOUS_USER_UUID), email=ANONYMOUS_USER_EMAIL)
    tool = PostgresTool(
        user=anonymous, current_chat_session_id=None, scope=DocumentScope()
    )
    for args in (
        {"table": "chat_session"},
        {"table": "chat_message"},
        {"table": "search_doc", "chat_message_id": 1},
    ):
        assert "unavailable to anonymous users" in _run_error(tool, **args)


def test_document_rows_and_truncation(tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    text = _run(tool_env.tool, table="document", title_contains=tag)
    assert "2 matching documents" in text
    assert f"Runbook 0 {tag}" in text
    assert f"Runbook 1 {tag}" in text
    assert f"https://example.com/pgtool_run_doc_0_{tag}" in text
    # Newest first.
    assert text.index(f"Runbook 0 {tag}") < text.index(f"Runbook 1 {tag}")


def _next_cursor(text: str) -> str | None:
    last_line = text.rsplit("\n", 1)[-1]
    prefix = "next_cursor: "
    return last_line[len(prefix) :] if last_line.startswith(prefix) else None


def test_document_paging(tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    tool = tool_env.tool
    first = _run(tool, table="document", title_contains=tag, limit=1)
    assert first.startswith("Showing 1 of 2 matching documents, newest first:")
    assert f"Runbook 0 {tag}" in first
    cursor = _next_cursor(first)
    assert cursor is not None

    # The page size may change between pages; the filters may not.
    last = _run(tool, table="document", title_contains=tag, limit=5, cursor=cursor)
    assert last.startswith("The last 1 matching documents:")
    assert f"Runbook 1 {tag}" in last
    assert f"Runbook 0 {tag}" not in last
    assert _next_cursor(last) is None

    other_filters = _run_error(
        tool, table="document", title_contains=f"Runbook 1 {tag}", cursor=cursor
    )
    assert "different filters" in other_filters
    assert "not a valid next_cursor" in _run_error(
        tool, table="document", title_contains=tag, cursor="not-a-cursor"
    )
    assert "only to document listings" in _run_error(
        tool, table="document", title_contains=tag, count=True, cursor=cursor
    )
    assert "only to document listings" in _run_error(
        tool, table="chat_session", cursor=cursor
    )

    # A cursor is tied to the agent's scope, too.
    scoped = _scoped_tool(
        tool_env, DocumentScope(attached_document_ids=[f"pgtool_run_doc_1_{tag}"])
    )
    assert "different filters" in _run_error(
        scoped, table="document", title_contains=tag, cursor=cursor
    )


def test_listed_documents_are_citable(tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    doc_0, doc_1 = f"pgtool_run_doc_0_{tag}", f"pgtool_run_doc_1_{tag}"
    result = _invoke_in_context(
        tool_env.tool,
        ToolContext(citation_mapping={4: doc_1}, next_citation_num=5),
        1,
        {"table": "document", "title_contains": tag},
    )
    assert isinstance(result.details, SearchDocsResponse)
    # A doc already cited keeps its number; new docs draw from this call's block.
    assert result.details.citation_mapping == {105: doc_0, 4: doc_1}
    assert [d.document_id for d in result.details.search_docs] == [doc_0, doc_1]
    assert result.details.search_docs[0].source_type == DocumentSource.WEB
    # The chat sidebar hides documents without a score.
    assert all(d.score is not None for d in result.details.search_docs)
    assert f"[105] Runbook 0 {tag}" in result.content
    assert f"[4] Runbook 1 {tag}" in result.content

    counted = _invoke(tool_env.tool, table="document", title_contains=tag, count=True)
    assert counted.details is None


def test_document_count_and_group_by(tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    assert "2 matching documents." in _run(
        tool_env.tool, table="document", title_contains=tag, count=True
    )

    grouped = _run(
        tool_env.tool,
        table="document",
        title_contains=tag,
        count=True,
        group_by="source",
    )
    assert "by source" in grouped
    assert "web: 2" in grouped

    by_owner = _run(
        tool_env.tool,
        table="document",
        title_contains=tag,
        count=True,
        group_by="owner",
    )
    assert f"owner_{tag}@example.com: 2" in by_owner

    dated = _run(
        tool_env.tool,
        table="document",
        title_contains=tag,
        updated_after=(datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        count=True,
    )
    assert "1 matching documents." in dated


def test_group_by_owner_without_owners(db_session: Session, tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    doc_id = f"pgtool_run_ownerless_{tag}"
    db_session.add(
        DbDocument(
            id=doc_id, semantic_id=f"Ownerless {tag}", kg_stage=KGStage.NOT_STARTED
        )
    )
    db_session.flush()
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=doc_id,
            connector_id=tool_env.cc_pair.connector_id,
            credential_id=tool_env.cc_pair.credential_id,
            has_been_indexed=True,
        )
    )
    db_session.commit()

    by_owner = _run(
        tool_env.tool,
        table="document",
        title_contains=f"Ownerless {tag}",
        count=True,
        group_by="owner",
    )
    assert by_owner.startswith("No matching documents have a recorded owner.")


def _scoped_tool(env: ToolEnv, scope: DocumentScope) -> PostgresTool:
    return PostgresTool(user=env.user, current_chat_session_id=None, scope=scope)


def test_scoped_tool_counts_only_the_knowledge(tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    tool = _scoped_tool(
        tool_env,
        DocumentScope(attached_document_ids=[f"pgtool_run_doc_0_{tag}"]),
    )
    counted = _run(tool, table="document", title_contains=tag, count=True)
    assert counted.startswith("Results are limited to this agent's knowledge")
    assert "1 matching documents." in counted

    listed = _run(tool, table="document", title_contains=tag)
    assert f"Runbook 0 {tag}" in listed
    assert f"Runbook 1 {tag}" not in listed

    # Chat history is the user's own and is never scoped.
    sessions = _run(tool, table="chat_session", description_contains=tag)
    assert not sessions.startswith("Results are limited")


def test_scope_that_matches_no_documents(tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    user_files_only = _scoped_tool(tool_env, DocumentScope(includes_user_files=True))
    for table in ("document", "hierarchy_node"):
        message = _run(user_files_only, table=table, count=True)
        assert message.startswith("This agent's knowledge is limited to uploaded files")

    no_sources = _scoped_tool(tool_env, DocumentScope(source_types=[]))
    message = _run(no_sources, table="document", title_contains=tag)
    assert message.startswith("This chat's search filters exclude every source")


def test_chat_session_query_excludes_current(tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    text = _run(
        _tool_excluding(tool_env, tool_env.session_current.id),
        table="chat_session",
        description_contains=tag,
    )
    assert f"Past scania conversation {tag}" in text
    assert f"/chat/{tool_env.session_other.id}" in text
    assert f"Current conversation {tag}" not in text

    # Without the exclusion, both sessions match.
    unexcluded = _run(tool_env.tool, table="chat_session", description_contains=tag)
    assert f"Current conversation {tag}" in unexcluded


def test_chat_message_query(tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    text = _run(
        _tool_excluding(tool_env, tool_env.session_current.id),
        table="chat_message",
        content_contains="scania",
        chat_session_id=str(tool_env.session_other.id),
    )
    assert f"scania answer with sources {tag}" in text
    assert f"message_id={tool_env.msg_cited.id}" in text
    assert f"session_link=/chat/{tool_env.session_other.id}" in text


def test_search_doc_cited_and_retrieved(tool_env: ToolEnv) -> None:
    tag = tool_env.tag
    cited = _run(
        tool_env.tool, table="search_doc", chat_message_id=tool_env.msg_cited.id
    )
    assert "2 matching cited documents" in cited
    assert f"[1] Source Doc 0 {tag}" in cited
    assert f"[2] Source Doc 1 {tag}" in cited
    assert f"Source Doc 2 {tag}" not in cited

    retrieved = _run(
        tool_env.tool,
        table="search_doc",
        chat_message_id=tool_env.msg_cited.id,
        cited_only=False,
    )
    assert "3 matching retrieved documents" in retrieved

    assert "2 matching cited documents." in _run(
        tool_env.tool,
        table="search_doc",
        chat_message_id=tool_env.msg_cited.id,
        count=True,
    )
