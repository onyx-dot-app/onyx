"""Guards the incognito context store's Redis contract.

Round trip, admitted writes, sliding TTL, teardown, corruption, image
references, and storage caps against real Redis. Each test runs
under a unique tenant so runs cannot collide, mirroring test_tenant_redis.py.
"""

import contextvars
import json
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Barrier, Event
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from redis.lock import Lock as RedisLock

from onyx.agents.compaction import working_messages
from onyx.agents.models import (
    CompactionCheckpoint,
    ExecutionStatus,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackendType, CacheLockLostError
from onyx.chat import incognito_context
from onyx.chat.chat_processing_checker import ChatTurnAdmission
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
    save_incognito_response,
    save_incognito_user_messages,
    teardown_incognito_session,
)
from onyx.chat.models import (
    ChatHistoryResult,
    ChatResponseSnapshot,
    IncognitoState,
    PromptMetadata,
    ResponseRecord,
)
from onyx.chat.prompt_formatting import prompt_metadata
from onyx.chat.prompt_utils import prepare_prompt
from onyx.chat.stream_buffer import _chunk_key
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.file_store.models import ChatFileType, ChatLoadedFile, FileToolMetadata
from onyx.llm.models import (
    AssistantMessage,
    Message,
    TextContent,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.models import ToolCall as AgentToolCall
from onyx.redis.redis_pool import get_raw_redis_client, get_redis_client
from onyx.utils.threadpool_concurrency import start_thread_future
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


def _seed_context(chat_session_id: UUID, messages: list[Message]) -> None:
    get_cache_backend().set(
        _context_key(chat_session_id),
        IncognitoState(messages=messages).model_dump_json(),
    )


def test_missing_key_loads_empty_history() -> None:
    assert load_incognito_context(uuid4()).messages == []


def test_corrupt_value_degrades_and_is_overwritable() -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    get_redis_client().set(_context_key(session_id), b"not json at all")

    context = load_incognito_context(session_id)
    assert context.messages == []

    save_incognito_user_messages(
        session_id, [UserMessage(content="fresh start")], admission=admission
    )
    assert load_incognito_context(session_id).messages[0].text == "fresh start"


@pytest.mark.parametrize("retained_response_index", [True, False])
def test_pre_upgrade_history_expires_without_blocking_new_turns(
    retained_response_index: bool,
) -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    # The deployed v2 schema has no root output IDs, even when child records remain.
    payload = {
        "messages": [
            {"role": "user", "id": "chat:1", "content": "Old question"},
            {
                "role": "assistant",
                "id": "old-output",
                "content": [{"type": "text", "text": "Old answer"}],
            },
        ],
        "previous_run_id": "2",
        "responses": {"2": {"replay_digest": "old", "agents": []}}
        if retained_response_index
        else {},
    }
    get_cache_backend().set(_context_key(session_id), json.dumps(payload))
    assert load_incognito_context(session_id).messages == []
    store = RedisChatHistoryStore(
        message_id=3,
        chat_session_id=session_id,
        admission=admission,
    )
    question = UserMessage(id="chat:3", content="New question")
    prepared, previous, checkpoint = store.prepare_messages(
        ChatHistoryResult(
            messages=[
                UserMessage(id="chat:1", content=""),
                AssistantMessage(id="chat:2", content=[]),
                question,
            ],
            input_start=2,
            all_injected_file_metadata={},
        ),
        "New question",
    )
    assert prepared.messages == [question]
    assert previous is None and checkpoint is None
    store.save_user_messages(prepared)
    response = _terminal_record(str(session_id), "New answer")
    save_incognito_response(
        session_id,
        response.run_id,
        checkpoint=response.checkpoint,
        admission=admission,
        message_id=4,
        messages=response.messages,
    )
    followup = UserMessage(id="chat:5", content="Continue")
    prepared, previous, _ = store.prepare_messages(
        ChatHistoryResult(
            messages=[question, AssistantMessage(id="chat:4", content=[]), followup],
            input_start=2,
            all_injected_file_metadata={},
        ),
        "Continue",
    )
    assert [message.text for message in prepared.messages] == [
        "New question",
        "New answer",
        "Continue",
    ]
    assert previous == response.run_id
    store.save_user_messages(prepared)
    assert len(load_incognito_context(session_id).messages) == 3
    admission.release()


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
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    get_cache_backend().set(_context_key(session_id), payload)

    assert load_incognito_context(session_id).messages == []
    save_incognito_user_messages(
        session_id, [UserMessage(content="fresh start")], admission=admission
    )
    assert load_incognito_context(session_id).messages[0].text == "fresh start"


def test_loaded_messages_are_isolated_from_other_loads_and_saved_state() -> None:
    session_id = uuid4()
    assistant = AssistantMessage(
        content=[AgentToolCall(id="call", name="search", arguments={"limit": 5})],
        metadata=PromptMetadata(token_count=12),
    )
    _seed_context(session_id, [assistant])
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
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    client = get_redis_client()

    save_incognito_user_messages(
        session_id, [UserMessage(content="first")], admission=admission
    )
    ttl_after_first = client.ttl(_context_key(session_id))
    assert 0 < ttl_after_first <= INCOGNITO_CONTEXT_TTL_SECONDS

    time.sleep(2)
    save_incognito_user_messages(
        session_id, [UserMessage(content="second")], admission=admission
    )
    ttl_after_second = client.ttl(_context_key(session_id))
    # A non-sliding TTL would have decayed by the sleep. A fresh save restarts it.
    assert ttl_after_second > INCOGNITO_CONTEXT_TTL_SECONDS - 2


def test_teardown_ends_the_context_and_fences_writers() -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    _seed_context(session_id, [_message("secret plans")])
    context = load_incognito_context(session_id)
    assert context.messages

    teardown_incognito_session(session_id)

    # Loads empty, and the tombstone refuses any save from an in-flight turn.
    assert load_incognito_context(session_id).messages == []
    with pytest.raises(RuntimeError, match="Could not save"):
        save_incognito_user_messages(
            session_id, [UserMessage(content="resurrected")], admission=admission
        )
    assert load_incognito_context(session_id).messages == []


@pytest.mark.parametrize("during_decode", [False, True])
def test_teardown_during_read_hides_fetched_content(during_decode: bool) -> None:
    session_id = uuid4()
    _seed_context(session_id, [_message("private")])
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
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    _seed_context(session_id, [_message("private")])
    cache = get_cache_backend()
    before = cache.get(_context_key(session_id))

    def update(state: IncognitoState | None) -> IncognitoState:
        assert state is not None
        cache.set(_tombstone_key(session_id), 1)
        return state.model_copy(
            update={"messages": [*state.messages, UserMessage(content="updated")]}
        )

    assert not _update_incognito_state(session_id, update, admission=admission)
    assert cache.get(_context_key(session_id)) == before
    assert load_incognito_context(session_id).messages == []


def test_image_references_survive_without_storing_bytes() -> None:
    """Replay reloads image content lazily from its stored file reference."""
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
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

    save_incognito_user_messages(session_id, [message], admission=admission)
    raw = get_cache_backend().get(_context_key(session_id))
    assert raw is not None
    stored_image = json.loads(raw)["messages"][0]["metadata"]["image_files"][0]
    assert stored_image["file_id"] == "f1"
    assert "content" not in stored_image
    with patch(
        "onyx.tools.file_snapshot.read_checkpoint_file", return_value=image.content
    ) as read_file:
        (loaded,) = load_incognito_context(session_id).messages
        read_file.assert_not_called()
        images = prompt_metadata(loaded).image_files
        assert images is not None and len(images) == 1
        assert images[0].content == image.content
        read_file.assert_called_once_with("f1")
    assert prompt_metadata(loaded).image_token_count == 85
    assert loaded.text == "see attached"


def test_tool_calls_round_trip() -> None:
    """Assistant tool calls and tool responses are part of history and must
    survive storage intact."""
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
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

    _seed_context(session_id, [])
    save_incognito_response(
        session_id,
        None,
        message_id=1,
        messages=[call, response],
        admission=admission,
    )
    loaded = load_incognito_context(session_id).messages

    assert [message.model_dump(exclude={"id"}) for message in loaded] == [
        message.model_dump(exclude={"id"}) for message in (call, response)
    ]
    assert all(message.id is not None for message in loaded)
    assert call.id is None and response.id is None


def test_message_count_cap_keeps_the_newest() -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    history = [_message(f"m{i}") for i in range(205)]

    _seed_context(session_id, history[:-1])
    save_incognito_user_messages(
        session_id, [UserMessage(content="m204")], admission=admission
    )
    loaded = load_incognito_context(session_id).messages

    assert len(loaded) == 200
    assert loaded[0].text == "m5"
    assert loaded[-1].text == "m204"


def test_byte_cap_drops_oldest_and_rejects_an_oversized_singleton() -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    big = "x" * 600_000
    oversized = "y" * 1_200_000

    save_incognito_user_messages(
        session_id, [UserMessage(content=big)], admission=admission
    )
    save_incognito_user_messages(
        session_id, [UserMessage(content=big + "newer")], admission=admission
    )
    loaded = load_incognito_context(session_id).messages
    assert len(loaded) == 1
    assert loaded[0].text.endswith("newer")

    admission.release()
    singleton_session = uuid4()
    admission.claim(singleton_session)
    with pytest.raises(ValueError, match="storage limit"):
        save_incognito_user_messages(
            singleton_session, [UserMessage(content=oversized)], admission=admission
        )
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
    run_id = str(uuid4())
    return ResponseRecord(
        agent_id=agent_id,
        run_id=run_id,
        status=RunStatus.COMPLETE,
        previous_run_id=previous_run_id,
        steps=[
            StepRecord(
                message=AssistantMessage(
                    id=f"{run_id}:0", content=[TextContent(text=text)]
                ),
                generation_status=ExecutionStatus.COMPLETE,
                tools={},
            )
        ],
    )


def test_response_retention_keeps_recent_root_history() -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    save_incognito_user_messages(
        session_id, [UserMessage(content="question")], admission=admission
    )
    with patch("onyx.chat.incognito_context._MAX_CONTEXT_BYTES", 3000):
        for message_id in range(1, 20):
            save_incognito_user_messages(
                session_id,
                [UserMessage(content=f"question {message_id}")],
                admission=admission,
            )
            reply = _terminal_record(str(session_id), f"answer {message_id}")
            save_incognito_response(
                session_id,
                reply.run_id,
                message_id=message_id,
                messages=reply.messages,
                admission=admission,
            )
        assert load_incognito_context(session_id).messages[-1].text == "answer 19"
        context = get_redis_client().get(_context_key(session_id))
        assert context is not None
        assert len(context) <= 3000


def test_terminal_write_rejects_oversize_without_changing_either_store() -> None:
    from onyx.chat.incognito_context import (
        save_incognito_response,
    )

    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    save_incognito_user_messages(
        session_id, [UserMessage(content="question")], admission=admission
    )
    client = get_redis_client()
    before = client.get(_context_key(session_id))
    reply = _terminal_record(str(uuid4()), "x" * 4000)
    with patch("onyx.chat.incognito_context._MAX_CONTEXT_BYTES", 1000):
        with pytest.raises(ValueError, match="storage limit"):
            save_incognito_response(
                session_id,
                reply.run_id,
                message_id=1,
                messages=reply.messages,
                admission=admission,
            )
    assert client.get(_context_key(session_id)) == before


def test_concurrent_terminal_writes_preserve_root_history() -> None:
    from onyx.chat import incognito_context

    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    root_id = str(session_id)
    incognito_context.save_incognito_user_messages(
        session_id, [UserMessage(content="question")], admission=admission
    )
    barrier = Barrier(2)
    replies = [_terminal_record(root_id, "first"), _terminal_record(root_id, "second")]

    def save(index: int, reply: ResponseRecord) -> None:
        barrier.wait(timeout=5)
        incognito_context.save_incognito_response(
            session_id,
            reply.run_id,
            message_id=index,
            messages=reply.messages,
            admission=admission,
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


def test_terminal_write_waiting_on_teardown_cannot_restore_replay_state() -> None:
    from onyx.chat import incognito_context

    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    incognito_context.save_incognito_user_messages(
        session_id, [UserMessage(content="question")], admission=admission
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
                        session_id,
                        reply.run_id,
                        message_id=1,
                        messages=reply.messages,
                        admission=admission,
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
        save_incognito_response,
    )

    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    root_id = str(session_id)
    save_incognito_user_messages(
        session_id, [UserMessage(content="question")], admission=admission
    )
    reply = _terminal_record(root_id, "accepted output " + "x" * 3000)
    messages = reply.messages
    with patch("onyx.chat.incognito_context._MAX_CONTEXT_BYTES", 4096):
        save_incognito_response(
            session_id,
            reply.run_id,
            message_id=1,
            messages=messages,
            admission=admission,
        )
        before = get_redis_client().get(_context_key(session_id))
        assert before is not None
        # Older cache entries can contain child records; root replay remains readable.
        legacy = json.loads(before)
        legacy["responses"]["1"]["agents"] = [{"agent_id": "old-child"}]
        before = json.dumps(legacy).encode()
        get_redis_client().set(_context_key(session_id), before)
        save_incognito_response(
            session_id,
            reply.run_id,
            message_id=1,
            messages=messages,
            admission=admission,
        )
        assert get_redis_client().get(_context_key(session_id)) == before
        with pytest.raises(ValueError, match="different content"):
            save_incognito_response(
                session_id,
                reply.run_id,
                message_id=1,
                messages=[AssistantMessage(content=[TextContent(text="different")])],
                admission=admission,
            )
        assert get_redis_client().get(_context_key(session_id)) == before
        assert before is not None and before.count(b"accepted output") == 1
        context = load_incognito_context(session_id)
        assert context.previous_run_id == reply.run_id
        assert [message.text for message in context.messages] == [
            "question",
            messages[0].text,
        ]
        save_incognito_user_messages(
            session_id, [UserMessage(content="followup")], admission=admission
        )
        assert [
            message.text for message in load_incognito_context(session_id).messages
        ] == ["followup"]
        assert load_incognito_context(session_id).responses == {}


@pytest.mark.parametrize("max_attempts", [1, 2])
def test_lost_lock_retries_against_fresh_envelope(max_attempts: int) -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    _seed_context(session_id, [_message("original")])
    cache = get_cache_backend()
    observed: list[str] = []

    def update(state: IncognitoState | None) -> IncognitoState:
        assert state is not None
        observed.append(state.messages[-1].text)
        if len(observed) == 1:
            cache.delete(f"{_context_key(session_id)}:lock")
            fresh = state.model_copy(
                update={"messages": [UserMessage(content="fresh")]}
            )
            cache.set(_context_key(session_id), fresh.model_dump_json())
        return state.model_copy(
            update={"messages": [*state.messages, UserMessage(content="updated")]}
        )

    assert _update_incognito_state(
        session_id, update, admission=admission, max_attempts=max_attempts
    ) == (max_attempts == 2)
    assert observed == (["original", "fresh"] if max_attempts == 2 else ["original"])
    assert [
        message.text for message in load_incognito_context(session_id).messages
    ] == (["fresh", "updated"] if max_attempts == 2 else ["fresh"])


def test_lost_lock_stops_after_bounded_retries() -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    _seed_context(session_id, [_message("original")])
    cache = get_cache_backend()
    calls = 0

    def update(state: IncognitoState | None) -> IncognitoState:
        nonlocal calls
        assert state is not None
        calls += 1
        cache.delete(f"{_context_key(session_id)}:lock")
        return state.model_copy(
            update={"messages": [*state.messages, UserMessage(content="updated")]}
        )

    assert not _update_incognito_state(
        session_id, update, admission=admission, max_attempts=2
    )
    assert calls == 2
    assert [
        message.text for message in load_incognito_context(session_id).messages
    ] == ["original"]


def test_rejected_transformation_keeps_stored_state_unchanged() -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    _seed_context(session_id, [_message("original")])
    cache = get_cache_backend()
    before = cache.get(_context_key(session_id))

    def update(state: IncognitoState | None) -> None:
        assert state is not None
        state.messages.clear()
        return None

    assert not _update_incognito_state(session_id, update, admission=admission)
    assert cache.get(_context_key(session_id)) == before
    with pytest.raises(ValueError, match="max_attempts"):
        _update_incognito_state(session_id, update, admission=admission, max_attempts=0)


@pytest.mark.parametrize("enqueue_fails", [False, True])
def test_busy_teardown_fences_access_then_retries(enqueue_fails: bool) -> None:
    session_id = uuid4()
    _seed_context(session_id, [_message("private")])
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
        _seed_context(session_id, [_message("private")])
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
    admission = ChatTurnAdmission(get_cache_backend())
    with (
        patch(
            "onyx.chat.incognito_context.app_configs.CACHE_BACKEND",
            CacheBackendType.POSTGRES,
        ),
        patch("onyx.chat.incognito_context.get_cache_backend") as factory,
    ):
        with pytest.raises(RuntimeError, match="Redis"):
            save_incognito_user_messages(
                uuid4(),
                [UserMessage(content="must not reach SQL")],
                admission=admission,
            )
        retry_incognito_teardowns()
        factory.assert_not_called()


@pytest.mark.parametrize("is_research", [False, True])
def test_root_sources_survive_temporary_response_round_trip(is_research: bool) -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    _seed_context(session_id, [UserMessage(content="Find evidence")])
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
        message_id=17,
        chat_session_id=session_id,
        admission=admission,
    )
    with patch(
        "onyx.chat.history_store.save_chat_response_to_db", return_value="Evidence [4]"
    ):
        store.save_response(snapshot)
        store.save_response(snapshot)
    prepared_history, previous_id, checkpoint = store.prepare_messages(
        ChatHistoryResult(
            messages=[
                AssistantMessage(id="chat:17", content=[]),
                UserMessage(content="Explain it"),
            ],
            input_start=1,
            all_injected_file_metadata={},
        ),
        "Explain it",
    )
    messages = prepared_history.messages
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


def test_regeneration_replaces_cached_answer_before_the_next_question() -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    question = UserMessage(
        id="chat:17", content="Original question", metadata=PromptMetadata()
    )
    old_answer = AssistantMessage(content=[TextContent(text="Old answer")])
    _seed_context(session_id, [question, old_answer])
    store = RedisChatHistoryStore(
        message_id=17,
        chat_session_id=session_id,
        admission=admission,
    )
    prepared_history, previous, checkpoint = store.prepare_messages(
        ChatHistoryResult(messages=[], input_start=0, all_injected_file_metadata={}),
        None,
    )
    selected = prepared_history.messages
    assert selected == [question]
    assert previous is None
    assert len(load_incognito_context(session_id).messages) == 2
    store.save_user_messages(
        ChatHistoryResult(
            messages=[question], input_start=0, all_injected_file_metadata={}
        )
    )
    assert load_incognito_context(session_id).messages == [question]
    replacement = _terminal_record("root", "Replacement answer")
    replacement.steps[0].message.metadata = PromptMetadata()
    replacement.input_messages = [question]
    incognito_context.save_incognito_response(
        session_id,
        replacement.run_id,
        message_id=19,
        messages=replacement.messages,
        admission=admission,
    )
    incoming = UserMessage(id="chat:20", content="Follow up")
    prepared_history, previous, checkpoint = store.prepare_messages(
        ChatHistoryResult(
            messages=[question, AssistantMessage(id="chat:19", content=[]), incoming],
            input_start=2,
            all_injected_file_metadata={},
        ),
        "Follow up",
    )
    messages = prepared_history.messages
    assert messages == [question, *replacement.messages, incoming]
    assert previous == replacement.run_id
    assert old_answer not in messages


@pytest.mark.parametrize("retention_limit", [4, 200])
@pytest.mark.parametrize("second_summary", [None, "", "Second summary"])
def test_parallel_responses_append_after_one_input_commit(
    retention_limit: int, second_summary: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    question = UserMessage(id="chat:17", content="Compare answers")
    store = RedisChatHistoryStore(
        message_id=17,
        chat_session_id=session_id,
        admission=admission,
    )
    store.save_user_messages(
        ChatHistoryResult(
            messages=[question], input_start=0, all_injected_file_metadata={}
        )
    )
    monkeypatch.setattr(incognito_context, "_MAX_CONTEXT_MESSAGES", retention_limit)
    first = _terminal_record("root", "First answer")
    first.input_messages = [question]
    first.checkpoint = CompactionCheckpoint(
        summary="First summary", covered_through_message_id=question.id or ""
    )
    first.steps.append(
        StepRecord(
            message=AssistantMessage(content=[TextContent(text="First conclusion")]),
            generation_status=ExecutionStatus.COMPLETE,
        )
    )
    second = _terminal_record("root", "Second answer")
    second.input_messages = [question]
    second.checkpoint = (
        CompactionCheckpoint(
            summary=second_summary, covered_through_message_id=question.id or ""
        )
        if second_summary is not None
        else None
    )
    for message_id, response in [(18, first), (19, second)]:
        incognito_context.save_incognito_response(
            session_id,
            response.run_id,
            checkpoint=response.checkpoint,
            message_id=message_id,
            messages=response.messages,
            admission=admission,
        )
    expected = [question, *first.messages, *second.messages]
    saved = load_incognito_context(session_id)
    assert [message.text for message in saved.messages] == [
        message.text for message in expected
    ]
    assert saved.previous_run_id == second.run_id
    if retention_limit == 200:
        incoming = UserMessage(id="chat:20", content="Continue")
        for message_id, chosen in [(18, first), (19, second)]:
            prepared, previous, checkpoint = store.prepare_messages(
                ChatHistoryResult(
                    messages=[
                        question,
                        AssistantMessage(id=f"chat:{message_id}", content=[]),
                        incoming,
                    ],
                    input_start=2,
                    all_injected_file_metadata={},
                ),
                "Continue",
            )
            assert [message.text for message in prepared.messages] == [
                question.text,
                *[message.text for message in chosen.messages],
                incoming.text,
            ]
            assert previous == chosen.run_id
            assert checkpoint == chosen.checkpoint
        store.save_user_messages(prepared)
        regeneration = RedisChatHistoryStore(
            message_id=20,
            chat_session_id=session_id,
            admission=admission,
        )
        _, _, checkpoint = regeneration.prepare_messages(
            ChatHistoryResult(
                messages=[
                    question,
                    AssistantMessage(id="chat:19", content=[]),
                    incoming,
                ],
                input_start=2,
                all_injected_file_metadata={},
            ),
            None,
        )
        assert checkpoint == second.checkpoint
        assert [
            message.text for message in load_incognito_context(session_id).messages
        ] == [message.text for message in prepared.messages]
        omitted, previous, checkpoint = store.prepare_messages(
            ChatHistoryResult(
                messages=[
                    question,
                    AssistantMessage(id="chat:18", content=[]),
                    incoming,
                ],
                input_start=2,
                all_injected_file_metadata={},
            ),
            "Continue",
        )
        assert [message.text for message in omitted.messages] == [
            question.text,
            incoming.text,
        ]
        assert previous is None
        assert checkpoint is None


def test_new_turn_rejects_previous_owner_history_writes() -> None:
    session_id = uuid4()
    cache = get_cache_backend()
    old = ChatTurnAdmission(cache)
    old.claim(session_id)
    question = UserMessage(id="chat:17", content="First question")
    incognito_context.save_incognito_user_messages(
        session_id, [question], admission=old
    )
    # Losing the lease does not stop a tool that is already executing.
    cache.delete(f"chatprocessing_owner_{session_id}")
    current = ChatTurnAdmission(cache)
    current.claim(session_id)
    incognito_context.save_incognito_user_messages(
        session_id,
        [UserMessage(id="chat:20", content="Next question")],
        admission=current,
    )
    before = cache.get(_context_key(session_id))
    response = _terminal_record("root", "Late answer")
    with pytest.raises(CacheLockLostError, match="admission was lost"):
        incognito_context.save_incognito_response(
            session_id,
            response.run_id,
            admission=old,
            message_id=18,
            messages=response.messages,
        )
    with pytest.raises(CacheLockLostError, match="admission was lost"):
        incognito_context.save_incognito_user_messages(
            session_id, [question], admission=old
        )
    assert cache.get(_context_key(session_id)) == before


def test_history_write_checks_ownership_after_serialization() -> None:
    session_id = uuid4()
    cache = get_cache_backend()
    admission = ChatTurnAdmission(cache)
    admission.claim(session_id)
    _seed_context(session_id, [UserMessage(content="Question")])
    before = cache.get(_context_key(session_id))
    serialize = IncognitoState.model_dump_json

    def serialize_after_expiry(state: IncognitoState) -> str:
        cache.delete(f"chatprocessing_owner_{session_id}")
        return serialize(state)

    response = _terminal_record("root", "Late answer")
    with patch.object(IncognitoState, "model_dump_json", serialize_after_expiry):
        with pytest.raises(CacheLockLostError, match="admission was lost"):
            incognito_context.save_incognito_response(
                session_id,
                response.run_id,
                admission=admission,
                message_id=18,
                messages=response.messages,
            )
    assert cache.get(_context_key(session_id)) == before


def test_takeover_after_owner_check_keeps_answer_before_new_question() -> None:
    session_id = uuid4()
    cache = get_cache_backend()
    old = ChatTurnAdmission(cache)
    old.claim(session_id)
    incognito_context.save_incognito_user_messages(
        session_id, [UserMessage(content="First question")], admission=old
    )
    response = _terminal_record("root", "First answer")
    checked = Event()
    finish_write = Event()
    check_owner = old.check_owner

    def pause_after_check(expected_session: UUID) -> None:
        check_owner(expected_session)
        checked.set()
        assert finish_write.wait(timeout=5)

    with patch.object(old, "check_owner", side_effect=pause_after_check):
        saving = start_thread_future(
            lambda: incognito_context.save_incognito_response(
                session_id,
                response.run_id,
                admission=old,
                message_id=18,
                messages=response.messages,
            ),
            name="test-old-incognito-response",
        )
        try:
            assert checked.wait(timeout=5)
            cache.delete(f"chatprocessing_owner_{session_id}")
            current = ChatTurnAdmission(cache)
            current.claim(session_id)
            # Ownership validation must run under the lock used by new input commits.
            with pytest.raises(RuntimeError, match="state is busy"):
                with _locked_incognito_state(session_id, blocking=False):
                    pytest.fail("History write released its lock before committing")
            incoming = start_thread_future(
                lambda: incognito_context.save_incognito_user_messages(
                    session_id,
                    [UserMessage(content="Next question")],
                    admission=current,
                ),
                name="test-new-incognito-input",
            )
        finally:
            finish_write.set()
            saving.result(timeout=5)
        incoming.result(timeout=5)
    assert [
        message.text for message in load_incognito_context(session_id).messages
    ] == [
        "First question",
        "First answer",
        "Next question",
    ]


@pytest.mark.parametrize("summary", ["Retained conversation facts.", ""])
def test_root_checkpoint_survives_temporary_response_and_next_input(
    summary: str,
) -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    question = UserMessage(id="chat:1", content="Original question")
    save_incognito_user_messages(session_id, [question], admission=admission)
    response = _terminal_record(str(session_id), "Answer")
    response.checkpoint = CompactionCheckpoint(
        summary=summary, covered_through_message_id="chat:1"
    )
    save_incognito_response(
        session_id,
        response.run_id,
        checkpoint=response.checkpoint,
        admission=admission,
        message_id=2,
        messages=response.messages,
    )
    stored = load_incognito_context(session_id)
    assert stored.responses["2"].checkpoint == response.checkpoint
    followup = UserMessage(id="chat:3", content="Follow up")
    store = RedisChatHistoryStore(
        message_id=3,
        chat_session_id=session_id,
        admission=admission,
    )
    prepared_history, previous, checkpoint = store.prepare_messages(
        ChatHistoryResult(
            messages=[AssistantMessage(id="chat:2", content=[]), followup],
            input_start=1,
            all_injected_file_metadata={},
        ),
        "Follow up",
    )
    messages = prepared_history.messages
    assert checkpoint == response.checkpoint
    assert previous == response.run_id
    assert messages[-1] == followup
    save_incognito_user_messages(session_id, [followup], admission=admission)
    assert (
        load_incognito_context(session_id).responses["2"].checkpoint
        == response.checkpoint
    )
    changed = response.model_copy(update={"checkpoint": None})
    with pytest.raises(ValueError, match="different content"):
        save_incognito_response(
            session_id,
            changed.run_id,
            checkpoint=changed.checkpoint,
            admission=admission,
            message_id=2,
            messages=response.messages,
        )
    admission.release()


@pytest.mark.parametrize("limit", ["messages", "bytes"])
@pytest.mark.parametrize("with_attachments", [False, True])
def test_retention_evicts_complete_turns(
    limit: str,
    with_attachments: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    group: list[Message] = []
    if with_attachments:
        group.append(
            UserMessage(
                id="file:one",
                content="Attachment",
                metadata=PromptMetadata(file_id="one"),
            )
        )
    question = UserMessage(id="chat:1", content="Find evidence")
    group.append(question)
    save_incognito_user_messages(
        session_id,
        group,
        admission=admission,
        file_metadata={
            "one": FileToolMetadata(
                file_id="one", filename="first.txt", approx_char_count=10
            )
        }
        if with_attachments
        else {},
    )
    response_messages: list[Message] = [
        AssistantMessage(
            id="call-message",
            content=[AgentToolCall(id="search-call", name="search", arguments={})],
        ),
        ToolResultMessage(
            id="evidence",
            tool_call_id="search-call",
            tool_name="search",
            content="evidence " * 100,
        ),
        AssistantMessage(id="answer", content=[TextContent(text="Old answer")]),
    ]
    save_incognito_response(
        session_id,
        None,
        message_id=2,
        messages=response_messages,
        admission=admission,
    )
    before = get_cache_backend().get(_context_key(session_id))
    assert before is not None
    if limit == "messages":
        monkeypatch.setattr(incognito_context, "_MAX_CONTEXT_MESSAGES", len(group) + 3)
    else:
        monkeypatch.setattr(incognito_context, "_MAX_CONTEXT_BYTES", len(before) + 1)
    followup = UserMessage(id="chat:3", content="New question")
    save_incognito_user_messages(session_id, [followup], admission=admission)
    retained = load_incognito_context(session_id)
    assert [(message.id, message.text) for message in retained.messages] == [
        (followup.id, followup.text)
    ]
    assert retained.responses == {}
    assert retained.file_metadata == {}
    answer = _terminal_record(str(session_id), "New answer")
    save_incognito_response(
        session_id,
        answer.run_id,
        checkpoint=answer.checkpoint,
        message_id=4,
        messages=answer.messages,
        admission=admission,
    )
    incoming = UserMessage(id="chat:5", content="Continue")
    store = RedisChatHistoryStore(
        message_id=5,
        chat_session_id=session_id,
    )
    prepared, _, _ = store.prepare_messages(
        ChatHistoryResult(
            messages=[
                question,
                AssistantMessage(id="chat:2", content=[]),
                followup,
                AssistantMessage(id="chat:4", content=[]),
                incoming,
            ],
            input_start=4,
            all_injected_file_metadata={},
        ),
        "Continue",
    )
    assert [(message.id, message.text) for message in prepared.messages] == [
        (message.id, message.text) for message in [followup, *answer.messages, incoming]
    ]
    admission.release()


@pytest.mark.parametrize("limit", ["messages", "bytes"])
def test_retention_rejects_an_oversized_current_turn_atomically(
    limit: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    question = UserMessage(id="chat:1", content="Compare answers")
    save_incognito_user_messages(session_id, [question], admission=admission)
    first = _terminal_record(str(session_id), "First answer")
    save_incognito_response(
        session_id,
        first.run_id,
        checkpoint=first.checkpoint,
        message_id=2,
        messages=first.messages,
        admission=admission,
    )
    before = get_cache_backend().get(_context_key(session_id))
    assert before is not None
    if limit == "messages":
        monkeypatch.setattr(incognito_context, "_MAX_CONTEXT_MESSAGES", 2)
    else:
        monkeypatch.setattr(incognito_context, "_MAX_CONTEXT_BYTES", len(before) + 1)
    second = _terminal_record(str(session_id), "Second answer")
    with pytest.raises(ValueError, match="storage limit"):
        save_incognito_response(
            session_id,
            second.run_id,
            checkpoint=second.checkpoint,
            message_id=3,
            messages=second.messages,
            admission=admission,
        )
    assert get_cache_backend().get(_context_key(session_id)) == before
    assert [
        (message.id, message.text)
        for message in load_incognito_context(session_id).messages
    ] == [(message.id, message.text) for message in [question, *first.messages]]
    admission.release()


def test_oversized_input_group_fails_without_saving_partial_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    monkeypatch.setattr(incognito_context, "_MAX_CONTEXT_MESSAGES", 2)
    with pytest.raises(ValueError, match="input exceeds its message storage limit"):
        save_incognito_user_messages(
            session_id,
            [
                UserMessage(
                    content="Attachment one", metadata=PromptMetadata(file_id="one")
                ),
                UserMessage(
                    content="Attachment two", metadata=PromptMetadata(file_id="two")
                ),
                UserMessage(id="chat:1", content="Compare attachments"),
            ],
            admission=admission,
        )
    assert load_incognito_context(session_id).messages == []


def test_temporary_filenames_survive_compaction_without_restoring_old_availability() -> (
    None
):
    session_id = uuid4()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(session_id)
    for number, name in [(1, "report.txt"), (2, "later.txt")]:
        file_id = str(number)
        save_incognito_user_messages(
            session_id,
            [
                UserMessage(
                    id=f"chat:{number}:file",
                    content=f"Private evidence {number}",
                    metadata=PromptMetadata(file_id=file_id),
                ),
                UserMessage(id=f"chat:{number}", content=f"Read file {number}"),
            ],
            admission=admission,
            file_metadata={
                **load_incognito_context(session_id).file_metadata,
                file_id: FileToolMetadata(
                    file_id=file_id,
                    filename=name,
                    approx_char_count=100,
                    staged_for_tools=True,
                ),
            },
        )
    canonical = FileToolMetadata(
        file_id="1",
        filename="unknown",
        approx_char_count=0,
        staged_for_tools=False,
    )
    store = RedisChatHistoryStore(
        message_id=1,
        chat_session_id=session_id,
        admission=admission,
    )
    branch = ChatHistoryResult(
        messages=[],
        input_start=0,
        all_injected_file_metadata={"1": canonical},
    )
    restored, _, _ = store.prepare_messages(branch, None)
    assert set(restored.all_injected_file_metadata) == {"1"}
    metadata = restored.all_injected_file_metadata["1"]
    assert metadata.filename == "report.txt"
    assert metadata.approx_char_count == 100
    assert metadata.staged_for_tools is False
    assert canonical.filename == "unknown"
    assert all(
        message.id not in {"chat:2:file", "chat:2"} for message in restored.messages
    )

    # Compaction omits the attachment body; its notice still needs the saved name.
    prompt = prepare_prompt(
        working_messages(
            [
                *restored.messages,
                AssistantMessage(
                    id="answer:1", content=[TextContent(text="Report reviewed.")]
                ),
                UserMessage(content="Ask about the earlier file"),
            ],
            CompactionCheckpoint(
                summary="Earlier report facts.", covered_through_message_id="answer:1"
            ),
        ),
        system_prompt=None,
        custom_agent_prompt=None,
        reminder_message=None,
        context_files=None,
        token_counter=len,
        all_injected_file_metadata=restored.all_injected_file_metadata,
        available_tool_names={"run_python"},
    )
    notice = prompt[-1].text
    assert "report.txt" in notice and "unknown" not in notice
    assert "no tool here can read them" in notice
    empty, _, _ = store.prepare_messages(
        branch.model_copy(update={"all_injected_file_metadata": {}}), None
    )
    assert empty.all_injected_file_metadata == {}
    store.save_user_messages(restored)
    assert set(load_incognito_context(session_id).file_metadata) == {"1"}
