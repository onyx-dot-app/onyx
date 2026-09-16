"""Guards the incognito persistence seams against real Postgres and Redis.

Two behaviors the feature rests on: save_chat_turn keeps the assistant row for
tracking but writes no text when content is not persisted, and the ephemeral
store round-trips a turn's messages so the next turn has its context. Run here
rather than as unit tests because both only mean something against the real
stores.
"""

from collections.abc import Generator
from io import BytesIO
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.incognito import delete_incognito_generated_files
from onyx.chat.incognito_context import (
    append_incognito_message,
    load_incognito_agent_history,
    load_incognito_agent_metadata,
    load_incognito_context,
    save_incognito_context,
    teardown_incognito_session,
)
from onyx.chat.models import RestoredAgent
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.context.messages import PromptMetadata
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    create_chat_session,
    get_or_create_root_message,
    reserve_chat_response_ids,
)
from onyx.db.chat_response import save_chat_turn
from onyx.db.file_record import (
    FileRecordNotFoundError,
    get_incognito_file_ids,
    get_session_ids_with_incognito_files,
)
from onyx.db.models import ChatMessage, ChatSession, User
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.models import AssistantMessage, TextContent, UserMessage
from onyx.redis.redis_pool import get_redis_client
from onyx.tools.models import ToolCallInfo
from shared_configs.contextvars import CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


@pytest.fixture
def owner(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "incognito-persist")
    yield user
    db_session.rollback()
    db_session.query(ChatSession).filter(ChatSession.user_id == user.id).delete()
    delete_test_user(db_session, user)
    db_session.commit()


def _new_session(db_session: Session, user_id: UUID) -> ChatSession:
    return create_chat_session(
        db_session=db_session,
        description="incognito",
        user_id=user_id,
        persona_id=None,
    )


def _reserve_assistant(db_session: Session, session_id: UUID) -> ChatMessage:
    root = get_or_create_root_message(chat_session_id=session_id, db_session=db_session)
    [message_id] = reserve_chat_response_ids(
        db_session=db_session,
        chat_session_id=session_id,
        parent_message_id=root.id,
        model_display_names=["test"],
    )
    message = db_session.get(ChatMessage, message_id)
    assert message is not None
    return message


def _search_doc(document_id: str) -> SearchDoc:
    return SearchDoc(
        document_id=document_id,
        chunk_ind=0,
        semantic_identifier="secret doc",
        blurb="confidential excerpt",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=["<hi>confidential</hi>"],
    )


def test_save_chat_turn_keeps_the_row_but_writes_no_text(
    db_session: Session, owner: User
) -> None:
    session = _new_session(db_session, owner.id)
    assistant = _reserve_assistant(db_session, session.id)

    doc = _search_doc("secret-doc-1")
    save_chat_turn(
        message_text="the acquisition target is confidential",
        reasoning_tokens="secret reasoning",
        tool_calls=[
            ToolCallInfo(
                message_id="test-run:0",
                parent_tool_call_id=None,
                turn_index=0,
                tab_index=0,
                tool_name="run_search",
                tool_call_id="call-1",
                tool_id=1,
                reasoning_tokens=None,
                tool_call_arguments={"query": "the confidential query"},
                tool_call_response="retrieved excerpt text",
                search_docs=[doc],
            )
        ],
        citation_to_doc={1: doc},
        all_search_docs={doc.document_id: doc},
        db_session=db_session,
        assistant_message=assistant,
        emitted_citations={1},
        persist_content=False,
    )
    db_session.commit()

    stored = db_session.get(ChatMessage, assistant.id)
    assert stored is not None
    # Row survives for tracking, with a real token count, but no text.
    assert stored.message == ""
    assert stored.reasoning_tokens is None
    assert stored.token_count > 0
    # Conversation-derived artifacts stay out too: no tool calls, no search
    # docs, no citations for a content-free turn.
    assert not stored.tool_calls
    assert not stored.search_docs
    assert not stored.citations


def test_save_chat_turn_persists_text_by_default(
    db_session: Session, owner: User
) -> None:
    session = _new_session(db_session, owner.id)
    assistant = _reserve_assistant(db_session, session.id)

    save_chat_turn(
        message_text="an ordinary answer",
        reasoning_tokens=None,
        tool_calls=[],
        citation_to_doc={},
        all_search_docs={},
        db_session=db_session,
        assistant_message=assistant,
    )
    db_session.commit()

    stored = db_session.get(ChatMessage, assistant.id)
    assert stored is not None
    assert stored.message == "an ordinary answer"


def test_turn_round_trips_through_the_store() -> None:
    """A turn appends the user message then the answer. The next turn loads both
    in order so the model sees its own context."""
    session_id = uuid4()
    try:
        append_incognito_message(
            session_id,
            UserMessage(
                content="what is our runway", metadata=PromptMetadata(token_count=4)
            ),
        )
        append_incognito_message(
            session_id,
            AssistantMessage(
                content=[TextContent(text="eighteen months")],
                metadata=PromptMetadata(token_count=2),
            ),
        )

        history = load_incognito_context(session_id).messages
        assert [(m.role, m.text) for m in history] == [
            ("user", "what is our runway"),
            ("assistant", "eighteen months"),
        ]
    finally:
        teardown_incognito_session(session_id)


def test_teardown_ends_the_session_immediately() -> None:
    session_id = uuid4()
    append_incognito_message(
        session_id,
        UserMessage(content="secret", metadata=PromptMetadata(token_count=1)),
    )
    assert load_incognito_context(session_id).messages

    teardown_incognito_session(session_id)

    assert load_incognito_context(session_id).messages == []


def test_teardown_clears_buffered_stream_chunks() -> None:
    """The stream buffer holds the streamed answer NDJSON, so teardown must
    delete it with the context instead of leaving it to the TTL."""
    session_id = uuid4()
    client = get_redis_client()
    chunk_key = f"chatstream_{session_id}_1:0"
    client.set(chunk_key, b"buffered answer text", ex=600)
    assert client.get(chunk_key) is not None

    teardown_incognito_session(session_id)

    assert client.get(chunk_key) is None


def _content_free_blob(session_id: UUID) -> str:
    """Save a blob the way a tool does inside a content-free turn."""
    token = CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.set(str(session_id))
    try:
        return get_default_file_store().save_file(
            content=BytesIO(b"generated chart bytes"),
            display_name="chart.png",
            file_origin=FileOrigin.CHAT_IMAGE_GEN,
            file_type="image/png",
        )
    finally:
        CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.reset(token)


def test_a_blob_is_stamped_when_it_is_saved(db_session: Session) -> None:
    """The stamp lands with the record, so no window exists where a blob is
    durable but unfindable."""
    session_id = uuid4()
    file_id = _content_free_blob(session_id)

    assert get_incognito_file_ids(str(session_id), db_session) == [file_id]


def test_teardown_deletes_the_stamped_blobs(db_session: Session) -> None:
    session_id = uuid4()
    file_id = _content_free_blob(session_id)
    file_store = get_default_file_store()

    assert delete_incognito_generated_files(session_id, db_session)

    with pytest.raises(FileRecordNotFoundError):
        file_store.read_file(file_id)
    assert get_incognito_file_ids(str(session_id), db_session) == []


def test_a_refused_deletion_keeps_the_stamp(db_session: Session) -> None:
    """A store outage must leave the blob findable for the sweep."""
    session_id = uuid4()
    file_id = _content_free_blob(session_id)
    file_store = get_default_file_store()

    with patch.object(
        type(file_store), "delete_file", side_effect=RuntimeError("store blip")
    ):
        assert not delete_incognito_generated_files(session_id, db_session)

    assert get_incognito_file_ids(str(session_id), db_session) == [file_id]
    assert str(session_id) in get_session_ids_with_incognito_files(db_session)

    assert delete_incognito_generated_files(session_id, db_session)
    with pytest.raises(FileRecordNotFoundError):
        file_store.read_file(file_id)


def test_the_sweep_lookup_samples_under_a_limit(db_session: Session) -> None:
    """The sweep always passes a limit, which turns on random sampling, so the
    DISTINCT lookup must stay valid Postgres with ORDER BY random() applied."""
    session_id = uuid4()
    _content_free_blob(session_id)

    assert len(get_session_ids_with_incognito_files(db_session, limit=1)) == 1

    assert delete_incognito_generated_files(session_id, db_session)


def _load_agent_history(
    session_id: UUID, message_ids: list[int]
) -> list[RestoredAgent]:
    return [
        load_incognito_agent_history(session_id, message_ids, agent.id)
        for agent in load_incognito_agent_metadata(session_id, message_ids)
    ]


def test_temporary_agent_history_sources_and_lifetime() -> None:
    from onyx.agents.transcript import AgentTranscript, RunStatus
    from onyx.chat.incognito_context import (
        INCOGNITO_CONTEXT_TTL_SECONDS,
        get_or_create_incognito_root_id,
        save_incognito_response,
    )

    session_id = uuid4()
    root_id, child_id = str(uuid4()), str(uuid4())
    child = AgentTranscript(
        agent_id=child_id,
        agent_path="/root/research",
        agent_description="Private task",
        run_id=str(uuid4()),
        status=RunStatus.COMPLETE,
        input_messages=[UserMessage(content="private question")],
        messages=[AssistantMessage(content=[TextContent(text="private answer")])],
    )
    root = AgentTranscript(
        agent_id=root_id,
        run_id=str(uuid4()),
        status=RunStatus.COMPLETE,
        messages=[],
        child_runs=[child],
    )
    key = f"incognito_ctx:{session_id}:agents"
    client = get_redis_client()
    try:
        append_incognito_message(session_id, UserMessage(content="root question"))
        assert get_or_create_incognito_root_id(session_id, root_id) == root_id
        assert get_or_create_incognito_root_id(session_id, str(uuid4())) == root_id
        assert _load_agent_history(session_id, [1]) == []
        assert child.run_id is not None
        sources = {child.run_id: {1: _search_doc("private-source")}}
        save_incognito_response(
            session_id, root, sources, message_id=1, messages=root.messages
        )
        save_incognito_response(
            session_id, root, sources, message_id=1, messages=root.messages
        )
        restored = _load_agent_history(session_id, [1])[1]
        assert len(restored.transcripts) == 1
        assert restored.transcripts[0].messages[0].text == "private answer"
        assert restored.sources[1].document_id == "private-source"

        next_child = child.model_copy(
            deep=True,
            update={
                "run_id": str(uuid4()),
                "previous_run_id": child.run_id,
                "input_messages": [UserMessage(content="next question")],
            },
        )
        next_root = root.model_copy(
            deep=True,
            update={
                "run_id": str(uuid4()),
                "previous_run_id": root.run_id,
                "child_runs": [next_child],
            },
        )
        save_incognito_response(
            session_id, next_root, {}, message_id=2, messages=next_root.messages
        )
        restored = _load_agent_history(session_id, [2, 1])[1]
        assert [run.run_id for run in restored.transcripts] == [
            child.run_id,
            next_child.run_id,
        ]
        assert restored.sources[1].document_id == "private-source"
        client.expire(key, 10)
        append_incognito_message(session_id, UserMessage(content="keep active"))
        assert client.ttl(key) >= INCOGNITO_CONTEXT_TTL_SECONDS - 2
        teardown_incognito_session(session_id)
        assert _load_agent_history(session_id, [2, 1]) == []
        with pytest.raises(RuntimeError, match="session ended"):
            save_incognito_response(
                session_id, next_root, {}, message_id=3, messages=next_root.messages
            )
        assert not client.exists(key)
        with pytest.raises(RuntimeError, match="session ended"):
            get_or_create_incognito_root_id(session_id, root_id)
    finally:
        teardown_incognito_session(session_id)


def test_incognito_context_and_predecessor_share_one_write() -> None:
    session_id = uuid4()
    try:
        append_incognito_message(session_id, UserMessage(content="question"))
        first = load_incognito_context(session_id)
        stale = load_incognito_context(session_id)
        first.messages.append(AssistantMessage(content=[TextContent(text="first")]))
        first.previous_run_id = "first-run"
        assert save_incognito_context(session_id, first)
        stale.messages.append(AssistantMessage(content=[TextContent(text="stale")]))
        stale.previous_run_id = "stale-run"
        assert not save_incognito_context(session_id, stale)
        restored = load_incognito_context(session_id)
        assert restored.messages[-1].text == "first"
        assert restored.previous_run_id == "first-run"
    finally:
        teardown_incognito_session(session_id)


def test_temporary_agents_require_live_session_context() -> None:
    from onyx.chat.incognito_context import get_or_create_incognito_root_id

    session_id = uuid4()
    client = get_redis_client()
    try:
        with pytest.raises(RuntimeError, match="session ended"):
            get_or_create_incognito_root_id(session_id, str(uuid4()))
        append_incognito_message(session_id, UserMessage(content="initial"))
        get_or_create_incognito_root_id(session_id, str(uuid4()))
        client.delete(f"incognito_ctx:{session_id}")
        with pytest.raises(RuntimeError, match="session ended"):
            get_or_create_incognito_root_id(session_id, str(uuid4()))
    finally:
        teardown_incognito_session(session_id)


@pytest.mark.parametrize("history_full", [False, True])
def test_incognito_response_restores_agents_without_database_content(
    db_session: Session, owner: User, history_full: bool
) -> None:
    from sqlalchemy import select

    from onyx.agents.runtime import Agent
    from onyx.agents.tools import AgentTool, ToolInvocation
    from onyx.chat.agent_registry import bind_chat_agents
    from onyx.chat.models import ChatResponseSnapshot, MessagePresentation
    from onyx.db.chat_response import save_chat_response
    from onyx.db.enums import IncognitoRecordMode
    from onyx.db.models import AgentRun, ChatSessionAgent
    from onyx.llm.interfaces import LLMUserIdentity
    from onyx.llm.models import ToolCall, ToolResult
    from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent

    session = _new_session(db_session, owner.id)
    session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    assistant = _reserve_assistant(db_session, session.id)
    db_session.commit()
    replies = iter(
        [
            AssistantMessage(
                content=[ToolCall(id="delegate", name="delegate", arguments={})]
            ),
            AssistantMessage(content=[TextContent(text="private child answer")]),
            AssistantMessage(content=[TextContent(text="private root answer")]),
        ]
    )
    llm = FakeModelClient(lambda *_: next(replies))
    identity = LLMUserIdentity(user_id=str(owner.id), session_id=str(session.id))
    child = Agent(llm)

    async def delegate(invocation: ToolInvocation) -> ToolResult:
        spawned = await invocation.agents.spawn_agent(
            child,
            name="research",
            description="private child task",
            messages=[UserMessage(content="private child question")],
            max_steps=1,
        )
        result = await invocation.agents.wait_run(spawned.run_id, timeout=3)
        assert result is not None
        return ToolResult(content=result.output.text)

    root = Agent(
        llm,
        tools=[
            AgentTool(
                name="delegate",
                description="",
                parameters={},
                execute_async=delegate,
            )
        ],
    )
    source = _search_doc("private-child-source")
    try:
        append_incognito_message(
            session.id, UserMessage(content="private root question")
        )
        coordinator = bind_chat_agents(
            root,
            previous_run_id=None,
            message_id=assistant.id,
            chat_session_id=session.id,
            persist_content=False,
            llm=llm,
            tools=[],
            user_identity=identity,
        )
        handles = []
        run_agent(
            root,
            messages=[UserMessage(content="private root question")],
            max_steps=2,
            coordinator=coordinator,
            runs=handles,
        )
        snapshot = handles[0].snapshot()
        from onyx.chat.presentation import project_response

        transcript = project_response(
            snapshot,
            response_id=assistant.id,
            tool_ids={},
            registrations=coordinator.registrations(),
        ).transcript
        assert transcript is not None
        child_run_id = transcript.child_runs[0].run_id
        assert child_run_id is not None
        response_snapshot = ChatResponseSnapshot(
            answer="private root answer",
            reasoning=None,
            request_params=None,
            citation_to_doc={},
            tool_calls=[],
            is_clarification=False,
            all_search_docs={source.document_id: source},
            pre_answer_processing_time=None,
            transcript=transcript,
            presentation=[
                MessagePresentation(
                    run_id=child_run_id,
                    step_index=0,
                    citation_documents={1: source.document_id},
                )
            ],
            cancelled=False,
        )
        if history_full:
            before = load_incognito_context(session.id)
            with patch("onyx.chat.incognito_context._MAX_CONTEXT_BYTES", 1):
                with pytest.raises(ValueError, match="storage limit"):
                    save_chat_response(
                        message_id=assistant.id, response=response_snapshot
                    )
            after = load_incognito_context(session.id)
            assert after.messages == before.messages
            assert after.previous_run_id == before.previous_run_id
            assert load_incognito_agent_metadata(session.id, [assistant.id]) == []
            return
        save_chat_response(message_id=assistant.id, response=response_snapshot)
        assert load_incognito_context(session.id).previous_run_id == transcript.run_id
        db_session.expire_all()
        assert assistant.message == "" and assistant.response_rendering is None
        assert (
            db_session.scalars(
                select(ChatSessionAgent).where(
                    ChatSessionAgent.chat_session_id == session.id
                )
            ).all()
            == []
        )
        assert (
            db_session.scalars(
                select(AgentRun).where(AgentRun.chat_message_id == assistant.id)
            ).all()
            == []
        )

        restored_root = Agent(llm)
        restored_coordinator = bind_chat_agents(
            restored_root,
            previous_run_id=transcript.run_id,
            message_id=assistant.id,
            chat_session_id=session.id,
            persist_content=False,
            llm=llm,
            tools=[],
            user_identity=identity,
        )
        assert restored_root.id == root.id
        saved_run = restored_coordinator._saved(child_run_id, restored_root.id)
        assert saved_run is not None
        assert saved_run.agent_id == child.id
        assert [message.text for message in saved_run.messages] == [
            "private child answer"
        ]

        assert (
            _load_agent_history(session.id, [assistant.id])[1].sources[1].document_id
            == source.document_id
        )
    finally:
        teardown_incognito_session(session.id)


@pytest.mark.parametrize("ancestor_finishes_first", [True, False])
def test_incognito_sibling_responses_keep_independent_agents_and_history(
    db_session: Session, owner: User, ancestor_finishes_first: bool
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from onyx.agents.transcript import AgentTranscript, RunStatus
    from onyx.chat.incognito_context import (
        get_or_create_incognito_root_id,
        save_incognito_response,
    )
    from onyx.db.agent_transcript import load_agent_branch

    session = _new_session(db_session, owner.id)
    ancestor = _reserve_assistant(db_session, session.id)
    sibling_ids = reserve_chat_response_ids(
        db_session=db_session,
        chat_session_id=session.id,
        parent_message_id=ancestor.id,
        model_display_names=["model-a", "model-b"],
    )
    [followup_id] = reserve_chat_response_ids(
        db_session=db_session,
        chat_session_id=session.id,
        parent_message_id=sibling_ids[0],
        model_display_names=["followup-a"],
    )
    db_session.commit()
    session_id = session.id
    ancestor_branch = load_agent_branch(ancestor.id).message_ids
    branches = {
        message_id: load_agent_branch(message_id).message_ids
        for message_id in sibling_ids
    }
    root_id = str(uuid4())
    ancestor_run = AgentTranscript(
        agent_id=root_id,
        run_id=str(uuid4()),
        status=RunStatus.COMPLETE,
        messages=[AssistantMessage(content=[TextContent(text="shared ancestor")])],
    )
    barrier = Barrier(2)

    def save_sibling(message_id: int) -> tuple[str, str]:
        assert get_or_create_incognito_root_id(session_id, str(uuid4())) == root_id
        root_run_id, child_id, child_run_id = str(uuid4()), str(uuid4()), str(uuid4())

        barrier.wait(timeout=5)

        child = AgentTranscript(
            agent_id=child_id,
            agent_path="/root/research",
            run_id=child_run_id,
            status=RunStatus.COMPLETE,
            messages=[
                AssistantMessage(content=[TextContent(text=f"answer {message_id}")])
            ],
        )
        result = AgentTranscript(
            agent_id=root_id,
            run_id=root_run_id,
            previous_run_id=ancestor_run.run_id if ancestor_finishes_first else None,
            status=RunStatus.COMPLETE,
            messages=[],
            child_runs=[child],
        )
        save_incognito_response(
            session_id,
            result,
            {child_run_id: {1: _search_doc(f"source-{message_id}")}},
            message_id=message_id,
            messages=result.messages,
        )
        return root_run_id, child_id

    try:
        append_incognito_message(session_id, UserMessage(content="question"))
        get_or_create_incognito_root_id(session_id, root_id)
        assert ancestor_run.run_id is not None

        if ancestor_finishes_first:
            save_incognito_response(
                session_id,
                ancestor_run,
                {},
                message_id=ancestor.id,
                messages=ancestor_run.messages,
            )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save_sibling, sibling_ids))
        if not ancestor_finishes_first:
            save_incognito_response(
                session_id,
                ancestor_run,
                {},
                message_id=ancestor.id,
                messages=ancestor_run.messages,
            )
        assert results[0][1] != results[1][1]
        for message_id, (run_id, child_id) in zip(sibling_ids, results, strict=True):
            agents = {
                agent.agent_path: agent
                for agent in _load_agent_history(session_id, branches[message_id])
            }
            expected_runs = (
                [ancestor_run.run_id, run_id] if ancestor_finishes_first else [run_id]
            )
            assert [run.run_id for run in agents["/root"].transcripts] == expected_runs
            child = agents["/root/research"]
            assert child.agent_id == child_id
            assert [run.messages[0].text for run in child.transcripts] == [
                f"answer {message_id}"
            ]
            assert child.sources[1].document_id == f"source-{message_id}"
        followup = _load_agent_history(
            session_id, load_agent_branch(followup_id).message_ids
        )
        assert followup[1].agent_id == results[0][1]
        assert followup[1].sources[1].document_id == f"source-{sibling_ids[0]}"
        assert len(_load_agent_history(session_id, ancestor_branch)) == 1
    finally:
        teardown_incognito_session(session_id)
