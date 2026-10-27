"""Guards the incognito context store's Redis contract.

Round trip, the compare-and-set that guards against concurrent turns, the
sliding TTL, teardown, corruption degrading to an ended session, image
stripping, and the storage caps, all against a real Redis. Each test runs
under a unique tenant so runs cannot collide, mirroring test_tenant_redis.py.
"""

import contextvars
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Barrier, Event
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from redis.lock import Lock as RedisLock

from onyx.agents.models import (
    ExecutionStatus,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackendType
from onyx.chat import incognito_context
from onyx.chat.history_store import RedisChatHistoryStore
from onyx.chat.incognito_context import (
    _PENDING_TEARDOWNS_KEY,
    INCOGNITO_CONTEXT_TTL_SECONDS,
    _context_key,
    _locked_incognito_state,
    _tombstone_key,
    _update_incognito_state,
    incognito_context_available,
    load_incognito_context,
    retry_incognito_teardowns,
    save_incognito_context,
    teardown_incognito_session,
)
from onyx.chat.models import (
    ChatResponseSnapshot,
    IncognitoContext,
    IncognitoState,
    PromptMetadata,
    ResponseRecord,
)
from onyx.chat.prompt_formatting import prompt_metadata
from onyx.chat.stream_buffer import _chunk_key
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.llm.models import (
    AssistantMessage,
    Message,
    TextContent,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.models import ToolCall as AgentToolCall
from onyx.redis.redis_pool import get_raw_redis_client, get_redis_client
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@pytest.fixture(autouse=True)
def isolated_tenant() -> Generator[str, None, None]:
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
    yield tenant
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    raw = get_raw_redis_client()
    keys = list(raw.scan_iter(match=f"{tenant}:*"))
    if keys:
        raw.delete(*keys)


def _message(text: str, message_type: MessageType = MessageType.USER) -> Message:
    metadata = PromptMetadata(token_count=len(text))
    if message_type == MessageType.ASSISTANT:
        return AssistantMessage(content=[TextContent(text=text)], metadata=metadata)
    return UserMessage(content=text, metadata=metadata)


def _save(chat_session_id: UUID, messages: list[Message], version: int = 0) -> bool:
    return save_incognito_context(
        chat_session_id, IncognitoContext(version=version, messages=messages)
    )


def test_missing_key_loads_empty_version_zero() -> None:
    context = load_incognito_context(uuid4())
    assert context.messages == []
    assert context.version == 0


def test_stale_version_save_is_discarded() -> None:
    """A concurrent turn that loaded the same version must not roll the
    winner's write back."""
    session_id = uuid4()
    assert _save(session_id, [_message("turn one")], version=0)

    # A racing writer that also loaded version 0 loses.
    assert not _save(session_id, [_message("stale rollback")], version=0)

    loaded = load_incognito_context(session_id)
    assert loaded.version == 1
    assert loaded.messages[0].text == "turn one"


def test_sequential_turns_chain_versions() -> None:
    session_id = uuid4()
    assert _save(session_id, [_message("one")], version=0)

    first = load_incognito_context(session_id)
    assert _save(session_id, first.messages + [_message("two")], first.version)

    second = load_incognito_context(session_id)
    assert second.version == 2
    assert [m.text for m in second.messages] == ["one", "two"]


def test_corrupt_value_degrades_and_is_overwritable() -> None:
    session_id = uuid4()
    get_redis_client().set(_context_key(session_id), b"not json at all")

    context = load_incognito_context(session_id)
    assert context.messages == []
    assert context.version == 0

    # The load/save pair recovers: expecting version 0 overwrites the garbage.
    assert _save(session_id, [_message("fresh start")], version=0)
    assert load_incognito_context(session_id).messages[0].text == "fresh start"


@pytest.mark.parametrize(
    "payload",
    [
        b'{"messages":[{"role":"unknown","content":"private"}]}',
        b'{"messages":[{"role":"user","content":"private",'
        b'"metadata":{"token_count":"invalid"}}]}',
    ],
)
def test_invalid_stored_message_is_not_replayed(payload: bytes) -> None:
    session_id = uuid4()
    get_cache_backend().set(_context_key(session_id), payload)

    assert load_incognito_context(session_id).messages == []
    assert _save(session_id, [_message("fresh start")])
    assert load_incognito_context(session_id).messages[0].text == "fresh start"


def test_loaded_messages_are_isolated_from_other_loads_and_saved_state() -> None:
    session_id = uuid4()
    assistant = AssistantMessage(
        content=[AgentToolCall(id="call", name="search", arguments={"limit": 5})],
        metadata=PromptMetadata(token_count=12),
    )
    assert _save(session_id, [assistant])
    first = load_incognito_context(session_id)
    second = load_incognito_context(session_id)
    loaded = first.messages[0]
    assert isinstance(loaded, AssistantMessage)

    loaded.tool_calls[0].arguments["limit"] = 10
    prompt_metadata(loaded).token_count = 99

    assert second.messages == [assistant]
    assert load_incognito_context(session_id).messages == [assistant]


def test_ttl_is_set_and_slides_on_save() -> None:
    session_id = uuid4()
    client = get_redis_client()

    assert _save(session_id, [_message("first")])
    ttl_after_first = client.ttl(_context_key(session_id))
    assert 0 < ttl_after_first <= INCOGNITO_CONTEXT_TTL_SECONDS

    time.sleep(2)
    first = load_incognito_context(session_id)
    assert _save(session_id, first.messages + [_message("second")], first.version)
    ttl_after_second = client.ttl(_context_key(session_id))
    # A non-sliding TTL would have decayed by the sleep. A fresh save restarts it.
    assert ttl_after_second > INCOGNITO_CONTEXT_TTL_SECONDS - 2


def test_teardown_ends_the_context_and_fences_writers() -> None:
    session_id = uuid4()
    assert _save(session_id, [_message("secret plans")])
    context = load_incognito_context(session_id)
    assert context.messages

    teardown_incognito_session(session_id)

    # Loads empty, and the tombstone refuses any save from an in-flight turn.
    assert load_incognito_context(session_id).messages == []
    assert not _save(session_id, [_message("resurrected")])
    assert load_incognito_context(session_id).messages == []


@pytest.mark.parametrize("during_decode", [False, True])
def test_teardown_during_read_hides_fetched_content(during_decode: bool) -> None:
    session_id = uuid4()
    assert _save(session_id, [_message("private")])
    cache = get_cache_backend()
    get = cache.get

    def get_then_end_session(key: str) -> bytes | None:
        content = get(key)
        cache.set(_tombstone_key(session_id), 1)
        return content

    decode_state = incognito_context._decode_state

    def decode_then_end_session(raw: bytes) -> IncognitoState:
        state = decode_state(raw)
        cache.set(_tombstone_key(session_id), 1)
        return state

    with patch("onyx.chat.incognito_context.get_cache_backend", return_value=cache):
        if during_decode:
            with patch.object(
                incognito_context, "_decode_state", side_effect=decode_then_end_session
            ):
                assert load_incognito_context(session_id).messages == []
        else:
            with patch.object(cache, "get", side_effect=get_then_end_session):
                assert load_incognito_context(session_id).messages == []


def test_teardown_during_update_prevents_commit() -> None:
    session_id = uuid4()
    assert _save(session_id, [_message("private")])
    cache = get_cache_backend()
    before = cache.get(_context_key(session_id))

    def update(state: IncognitoState | None) -> IncognitoState:
        assert state is not None
        cache.set(_tombstone_key(session_id), 1)
        return state.model_copy(update={"version": state.version + 1})

    assert not _update_incognito_state(session_id, update)
    assert cache.get(_context_key(session_id)) == before
    assert load_incognito_context(session_id).messages == []


def test_images_are_stripped_before_storage() -> None:
    """File bytes do not round-trip JSON, so save must drop them rather than
    fail the turn or store binary content."""
    session_id = uuid4()
    image = ChatLoadedFile(
        file_id="f1",
        content=b"\x89PNG\r\n",
        file_type=ChatFileType.IMAGE,
        filename="chart.png",
        content_text=None,
        token_count=0,
    )
    message = UserMessage(
        content="see attached",
        metadata=PromptMetadata(
            token_count=100, image_files=[image], image_token_count=85
        ),
    )

    assert _save(session_id, [message])
    (loaded,) = load_incognito_context(session_id).messages

    assert prompt_metadata(loaded).image_files is None
    assert prompt_metadata(loaded).image_token_count == 0
    assert loaded.text == "see attached"


def test_tool_calls_round_trip() -> None:
    """Assistant tool calls and tool responses are part of history and must
    survive storage intact."""
    session_id = uuid4()
    call = AssistantMessage(
        content=[
            TextContent(text=""),
            *(
                [
                    AgentToolCall(
                        id="call_1",
                        name="run_search",
                        arguments={"query": "churn", "limit": 5, "nested": {"a": [1]}},
                    )
                ]
                or []
            ),
        ],
        metadata=PromptMetadata(token_count=12),
    )
    response = ToolResultMessage(
        content="3 documents found",
        tool_call_id="call_1",
        tool_name="",
        metadata=PromptMetadata(token_count=4),
    )

    assert _save(session_id, [call, response])
    loaded = load_incognito_context(session_id).messages

    assert loaded == [call, response]


def test_message_count_cap_keeps_the_newest() -> None:
    session_id = uuid4()
    history = [_message(f"m{i}") for i in range(205)]

    assert _save(session_id, history)
    loaded = load_incognito_context(session_id).messages

    assert len(loaded) == 200
    assert loaded[0].text == "m5"
    assert loaded[-1].text == "m204"


def test_byte_cap_drops_oldest_and_rejects_an_oversized_singleton() -> None:
    session_id = uuid4()
    big = "x" * 600_000
    oversized = "y" * 1_200_000

    assert _save(session_id, [_message(big), _message(big + "newer")])
    loaded = load_incognito_context(session_id).messages
    assert len(loaded) == 1
    assert loaded[0].text.endswith("newer")

    singleton_session = uuid4()
    with pytest.raises(ValueError, match="storage limit"):
        _save(singleton_session, [_message(oversized)])
    assert load_incognito_context(singleton_session).messages == []


def test_availability_follows_the_cache_backend() -> None:
    """USAGE_ONLY content must never reach Postgres, so the Postgres cache
    backend (Lite) means the feature is absent."""
    with patch("onyx.chat.incognito_context.app_configs") as mock_configs:
        mock_configs.CACHE_BACKEND = CacheBackendType.REDIS
        assert incognito_context_available()
        mock_configs.CACHE_BACKEND = CacheBackendType.POSTGRES
        assert not incognito_context_available()


def _terminal_record(
    agent_id: str, text: str, previous_run_id: str | None = None
) -> ResponseRecord:
    return ResponseRecord(
        agent_id=agent_id,
        run_id=str(uuid4()),
        status=RunStatus.COMPLETE,
        previous_run_id=previous_run_id,
        steps=[
            StepRecord(
                message=AssistantMessage(content=[TextContent(text=text)]),
                generation_status=ExecutionStatus.COMPLETE,
                tools={},
            )
        ],
    )


def test_response_retention_keeps_root_usable_and_reports_expired_child_history() -> (
    None
):
    from onyx.chat.incognito_context import (
        append_incognito_message,
        load_incognito_agent_history,
        save_incognito_response,
    )

    session_id = uuid4()
    root_id, child_id = str(session_id), str(uuid4())
    append_incognito_message(session_id, UserMessage(content="question"))
    first_child = _terminal_record(child_id, "child result " + "x" * 250)
    first_child.agent_path = "/root/research"
    first = _terminal_record(root_id, "root result " + "a" * 250)
    first.child_runs = [first_child]
    second_child = _terminal_record(child_id, "continued result", first_child.run_id)
    second_child.agent_path = first_child.agent_path
    second = _terminal_record(root_id, "next answer", first.run_id)
    second.child_runs = [second_child]
    with patch("onyx.chat.incognito_context._MAX_CONTEXT_BYTES", 3000):
        save_incognito_response(
            session_id,
            first,
            {},
            message_id=1,
            messages=first.messages,
        )
        save_incognito_response(
            session_id,
            second,
            {},
            message_id=2,
            messages=second.messages,
        )
        with pytest.raises(ValueError, match="expired"):
            load_incognito_agent_history(session_id, [2, 1], child_id)
        for message_id in range(3, 15):
            reply = _terminal_record(root_id, f"answer {message_id}")
            save_incognito_response(
                session_id,
                reply,
                {},
                message_id=message_id,
                messages=reply.messages,
            )
        assert load_incognito_context(session_id).messages[-1].text == "answer 14"
        client = get_redis_client()
        context = client.get(_context_key(session_id))
        assert context is not None
        assert len(context) <= 3000


def test_terminal_write_rejects_oversize_without_changing_either_store() -> None:
    from onyx.chat.incognito_context import (
        append_incognito_message,
        save_incognito_response,
    )

    session_id = uuid4()
    append_incognito_message(session_id, UserMessage(content="question"))
    client = get_redis_client()
    before = client.get(_context_key(session_id))
    reply = _terminal_record(str(uuid4()), "x" * 4000)
    with patch("onyx.chat.incognito_context._MAX_CONTEXT_BYTES", 1000):
        with pytest.raises(ValueError, match="storage limit"):
            save_incognito_response(
                session_id,
                reply,
                {},
                message_id=1,
                messages=reply.messages,
            )
    assert client.get(_context_key(session_id)) == before


def test_concurrent_terminal_writes_preserve_root_and_child_records() -> None:
    from onyx.chat import incognito_context

    session_id = uuid4()
    root_id = str(session_id)
    incognito_context.append_incognito_message(
        session_id, UserMessage(content="question")
    )
    barrier = Barrier(2)
    replies = [_terminal_record(root_id, "first"), _terminal_record(root_id, "second")]
    for reply in replies:
        reply.child_runs = [_terminal_record(str(uuid4()), f"child of {reply.run_id}")]

    def save(index: int, reply: ResponseRecord) -> None:
        barrier.wait(timeout=5)
        incognito_context.save_incognito_response(
            session_id, reply, {}, message_id=index, messages=reply.messages
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks = [
            executor.submit(contextvars.copy_context().run, save, index, reply)
            for index, reply in enumerate(replies, 1)
        ]
        for task in tasks:
            task.result(timeout=10)
    assert {
        message.text for message in load_incognito_context(session_id).messages
    } == {"question", "first", "second"}
    assert len(incognito_context._incognito_records(session_id, [2, 1])) == 2


def test_terminal_write_waiting_on_teardown_cannot_restore_replay_state() -> None:
    from onyx.chat import incognito_context

    session_id = uuid4()
    incognito_context.append_incognito_message(
        session_id, UserMessage(content="question")
    )
    reply = _terminal_record(str(uuid4()), "answer")
    acquire_started = Event()
    acquire = RedisLock.acquire

    def acquire_with_signal(
        lock: RedisLock, blocking: bool = True, blocking_timeout: float | None = None
    ) -> bool:
        acquire_started.set()
        return bool(acquire(lock, blocking=blocking, blocking_timeout=blocking_timeout))

    with ThreadPoolExecutor(max_workers=1) as executor:
        with _locked_incognito_state(session_id):
            with patch.object(RedisLock, "acquire", acquire_with_signal):
                future = executor.submit(
                    copy_context().run,
                    lambda: incognito_context.save_incognito_response(
                        session_id, reply, {}, message_id=1, messages=reply.messages
                    ),
                )
                assert acquire_started.wait(timeout=2)
                assert not future.done()
                # Commit teardown while the writer waits for the same session lock.
                get_cache_backend().set(_tombstone_key(session_id), 1)
                get_cache_backend().delete(_context_key(session_id))
        with pytest.raises(RuntimeError, match="session ended"):
            future.result(timeout=10)
    assert get_cache_backend().exists(_tombstone_key(session_id))
    assert get_cache_backend().get(_context_key(session_id)) is None


def test_root_replay_is_stored_once_and_conflicting_retries_are_rejected() -> None:
    from onyx.chat.incognito_context import (
        append_incognito_message,
        load_incognito_agent_metadata,
        save_incognito_response,
    )

    session_id = uuid4()
    root_id = str(session_id)
    append_incognito_message(session_id, UserMessage(content="question"))
    reply = _terminal_record(root_id, "accepted output " + "x" * 3000)
    messages = reply.messages
    with patch("onyx.chat.incognito_context._MAX_CONTEXT_BYTES", 4096):
        save_incognito_response(session_id, reply, {}, message_id=1, messages=messages)
        before = get_redis_client().get(_context_key(session_id))
        save_incognito_response(session_id, reply, {}, message_id=1, messages=messages)
        assert get_redis_client().get(_context_key(session_id)) == before
        with pytest.raises(ValueError, match="different content"):
            save_incognito_response(
                session_id,
                reply,
                {},
                message_id=1,
                messages=[AssistantMessage(content=[TextContent(text="different")])],
            )
        assert get_redis_client().get(_context_key(session_id)) == before
        assert before is not None and before.count(b"accepted output") == 1
        assert load_incognito_agent_metadata(session_id, [1]) == []
        context = load_incognito_context(session_id)
        assert context.previous_run_id == reply.run_id
        assert [message.text for message in context.messages] == [
            "question",
            messages[0].text,
        ]
        append_incognito_message(session_id, UserMessage(content="followup"))
        assert load_incognito_context(session_id).messages[-2].text == messages[0].text


@pytest.mark.parametrize("max_attempts", [1, 2])
def test_lost_lock_retries_against_fresh_envelope(max_attempts: int) -> None:
    session_id = uuid4()
    assert _save(session_id, [_message("original")])
    cache = get_cache_backend()
    observed: list[int] = []

    def update(state: IncognitoState | None) -> IncognitoState:
        assert state is not None
        observed.append(state.version)
        if len(observed) == 1:
            cache.delete(f"{_context_key(session_id)}:lock")
            fresh = state.model_copy(update={"version": 2})
            cache.set(_context_key(session_id), fresh.model_dump_json())
        return state.model_copy(update={"version": state.version + 1})

    assert _update_incognito_state(session_id, update, max_attempts=max_attempts) == (
        max_attempts == 2
    )
    assert observed == ([1, 2] if max_attempts == 2 else [1])
    assert load_incognito_context(session_id).version == (3 if max_attempts == 2 else 2)


def test_lost_lock_stops_after_bounded_retries() -> None:
    session_id = uuid4()
    assert _save(session_id, [_message("original")])
    cache = get_cache_backend()
    calls = 0

    def update(state: IncognitoState | None) -> IncognitoState:
        nonlocal calls
        assert state is not None
        calls += 1
        cache.delete(f"{_context_key(session_id)}:lock")
        return state.model_copy(update={"version": state.version + 1})

    assert not _update_incognito_state(session_id, update, max_attempts=2)
    assert calls == 2
    assert load_incognito_context(session_id).version == 1


def test_rejected_transformation_keeps_stored_state_unchanged() -> None:
    session_id = uuid4()
    assert _save(session_id, [_message("original")])
    cache = get_cache_backend()
    before = cache.get(_context_key(session_id))

    def update(state: IncognitoState | None) -> None:
        assert state is not None
        state.messages.clear()
        return None

    assert not _update_incognito_state(session_id, update)
    assert cache.get(_context_key(session_id)) == before
    with pytest.raises(ValueError, match="max_attempts"):
        _update_incognito_state(session_id, update, max_attempts=0)


@pytest.mark.parametrize("enqueue_fails", [False, True])
def test_busy_teardown_fences_access_then_retries(enqueue_fails: bool) -> None:
    session_id = uuid4()
    assert _save(session_id, [_message("private")])
    cache = get_cache_backend()
    cache.set(_chunk_key(session_id, 1, 0), b"private stream")
    with _locked_incognito_state(session_id):
        with patch("onyx.chat.incognito_context._STATE_LOCK_WAIT_SECONDS", 0):
            with patch(
                "onyx.chat.incognito_context._enqueue_incognito_teardown_retry",
                side_effect=RuntimeError("offline") if enqueue_fails else None,
            ):
                teardown_incognito_session(session_id)
        assert load_incognito_context(session_id).messages == []
        assert str(session_id).encode() in cache.set_members(
            _PENDING_TEARDOWNS_KEY, limit=100
        )
        retry_incognito_teardowns()
        assert str(session_id).encode() in cache.set_members(
            _PENDING_TEARDOWNS_KEY, limit=100
        )
    retry_incognito_teardowns()
    assert cache.exists(_tombstone_key(session_id))
    assert cache.get(_context_key(session_id)) is None
    assert cache.get(_chunk_key(session_id, 1, 0)) is None
    assert str(session_id).encode() not in cache.set_members(
        _PENDING_TEARDOWNS_KEY, limit=100
    )


def test_busy_cleanup_does_not_block_other_sessions() -> None:
    busy, available = uuid4(), uuid4()
    for session_id in (busy, available):
        assert _save(session_id, [_message("private")])
    cache = get_cache_backend()
    with _locked_incognito_state(busy):
        with (
            patch("onyx.chat.incognito_context._STATE_LOCK_WAIT_SECONDS", 0),
            patch("onyx.chat.incognito_context._enqueue_incognito_teardown_retry"),
        ):
            teardown_incognito_session(busy)
            teardown_incognito_session(available)
        assert str(busy).encode() in cache.set_members(
            _PENDING_TEARDOWNS_KEY, limit=100
        )
        assert str(available).encode() not in cache.set_members(
            _PENDING_TEARDOWNS_KEY, limit=100
        )
        assert cache.get(_context_key(available)) is None
    retry_incognito_teardowns()
    assert cache.get(_context_key(busy)) is None
    assert str(busy).encode() not in cache.set_members(
        _PENDING_TEARDOWNS_KEY, limit=100
    )


def test_cleanup_retry_bounds_each_batch_and_retains_remaining_work() -> None:
    cache = get_cache_backend()
    sessions = [uuid4() for _ in range(105)]
    for session_id in sessions:
        cache.set_add(_PENDING_TEARDOWNS_KEY, str(session_id))
    retry_incognito_teardowns()
    pending = cache.set_members(_PENDING_TEARDOWNS_KEY, limit=200)
    assert len(pending) == 5
    retry_incognito_teardowns()
    assert cache.set_members(_PENDING_TEARDOWNS_KEY, limit=200) == []


def test_postgres_rejection_happens_before_cache_access() -> None:
    with (
        patch(
            "onyx.chat.incognito_context.app_configs.CACHE_BACKEND",
            CacheBackendType.POSTGRES,
        ),
        patch("onyx.chat.incognito_context.get_cache_backend") as factory,
    ):
        with pytest.raises(RuntimeError, match="Redis"):
            _save(uuid4(), [_message("must not reach SQL")])
        retry_incognito_teardowns()
        factory.assert_not_called()


@pytest.mark.parametrize("is_research", [False, True])
def test_root_sources_survive_temporary_response_round_trip(is_research: bool) -> None:
    session_id = uuid4()
    assert _save(session_id, [UserMessage(content="Find evidence")])
    document = SearchDoc(
        document_id="source",
        chunk_ind=0,
        semantic_identifier="Reference",
        link="https://example.com/reference",
        blurb="Evidence",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    result = ToolResultMessage(
        tool_call_id="call",
        tool_name="research_agent" if is_research else "web_search",
        content="Evidence [4]",
        details=(
            ResearchAgentCallResult(
                intermediate_report="Evidence [4]", citation_mapping={4: document}
            )
            if is_research
            else SearchDocsResponse(search_docs=[], citation_mapping={4: "source"})
        ),
    )
    record = ResponseRecord(
        run_id="17",
        agent_id=str(session_id),
        status=RunStatus.COMPLETE,
        steps=[
            StepRecord(
                message=AssistantMessage(
                    content=[
                        AgentToolCall(id="call", name=result.tool_name, arguments={})
                    ]
                ),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    "call": ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE, result=result
                    )
                },
            )
        ],
    )
    snapshot = ChatResponseSnapshot(
        answer="Evidence [4]",
        reasoning=None,
        request_params=None,
        citation_to_doc={4: document},
        tool_calls=[],
        is_clarification=False,
        all_search_docs={"source": document},
        pre_answer_processing_time=None,
        response=record,
        cancelled=False,
    )
    store = RedisChatHistoryStore(
        message_id=17, chat_session_id=session_id, visible_message_ids=()
    )
    with patch(
        "onyx.chat.history_store.save_chat_response_to_db", return_value="Evidence [4]"
    ):
        store.save_response(snapshot)
        store.save_response(snapshot)
    messages, previous_id = store.prepare_messages(
        [UserMessage(content="Explain it")], None, "Explain it"
    )
    assert previous_id == "17"
    restored = messages[-2]
    assert isinstance(restored, ToolResultMessage)
    if is_research:
        assert isinstance(restored.details, ResearchAgentCallResult)
        assert restored.details.citation_mapping == {4: document}
    else:
        assert isinstance(restored.details, SearchDocsResponse)
        assert restored.details.search_docs == [document]
        assert restored.details.citation_mapping == {4: "source"}
        assert isinstance(result.details, SearchDocsResponse)
        assert result.details.search_docs == []
    restored.content = "changed locally"
    assert load_incognito_context(session_id).messages[-1].content == "Evidence [4]"
