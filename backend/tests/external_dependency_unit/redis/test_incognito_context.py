"""Guards the incognito context store's Redis contract.

Round trip, the compare-and-set that guards against concurrent turns, the
sliding TTL, teardown, corruption degrading to an ended session, image
stripping, and the storage caps, all against a real Redis. Each test runs
under a unique tenant so runs cannot collide, mirroring test_tenant_redis.py.
"""

import time
from collections.abc import Generator
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from onyx.agents.execution_records import RunStatus
from onyx.cache.interface import CacheBackendType
from onyx.chat.incognito_context import (
    INCOGNITO_CONTEXT_TTL_SECONDS,
    IncognitoContext,
    _context_key,
    _IncognitoWrite,
    incognito_context_available,
    load_incognito_context,
    save_incognito_context,
    teardown_incognito_session,
)
from onyx.chat.llm_step import PromptMetadata, prompt_metadata
from onyx.chat.models import ResponseRecord
from onyx.chat.response_items import build_response_items, messages_from_items
from onyx.configs.constants import MessageType
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
from onyx.redis.tenant_redis_client import TenantRedisPipeline
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


def test_previous_context_shape_remains_readable() -> None:
    import json

    session_id = uuid4()
    legacy = [
        {"message": "question", "message_type": "user", "token_count": 1},
        {
            "message": "checking",
            "message_type": "assistant",
            "token_count": 2,
            "tool_calls": [
                {
                    "tool_call_id": "call",
                    "tool_name": "lookup",
                    "tool_arguments": {"query": "value"},
                    "token_count": 1,
                }
            ],
        },
        {
            "message": "result",
            "message_type": "tool_call_response",
            "tool_call_id": "call",
            "token_count": 1,
        },
    ]
    get_redis_client().set(_context_key(session_id), "3:" + json.dumps(legacy))
    context = load_incognito_context(session_id)
    assert context.version == 3
    assert [item.text for item in context.messages] == [
        "question",
        "checking",
        "result",
    ]
    assert isinstance(context.messages[1], AssistantMessage)
    assert context.messages[1].tool_calls[0].id == "call"
    assert context.messages[1].tool_calls[0].arguments == {"query": "value"}
    assert save_incognito_context(session_id, context)
    assert load_incognito_context(session_id).messages == context.messages


def _archive(key: str) -> dict[bytes, bytes]:
    with get_redis_client().pipeline() as pipeline:
        pipeline.watch(key)
        return pipeline.hgetall_watched(key)


def _terminal_record(
    agent_id: str, text: str, previous_run_id: str | None = None
) -> ResponseRecord:
    return ResponseRecord(
        agent_id=agent_id,
        run_id=str(uuid4()),
        status=RunStatus.COMPLETE,
        previous_run_id=previous_run_id,
        items=build_response_items(
            "test-generation", [AssistantMessage(content=[TextContent(text=text)])], []
        ),
    )


def test_response_retention_keeps_root_usable_and_reports_expired_child_history() -> (
    None
):
    from onyx.chat.incognito_context import (
        append_incognito_message,
        get_or_create_incognito_root_id,
        load_incognito_agent_history,
        save_incognito_response,
    )

    session_id = uuid4()
    root_id, child_id = str(uuid4()), str(uuid4())
    append_incognito_message(session_id, UserMessage(content="question"))
    get_or_create_incognito_root_id(session_id, root_id)
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
            messages=messages_from_items(first.items),
        )
        save_incognito_response(
            session_id,
            second,
            {},
            message_id=2,
            messages=messages_from_items(second.items),
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
                messages=messages_from_items(reply.items),
            )
        assert load_incognito_context(session_id).messages[-1].text == "answer 14"
        client = get_redis_client()
        context = client.get(_context_key(session_id))
        archive = _archive(f"incognito_ctx:{session_id}:agents")
        assert context is not None
        assert (
            len(context) + sum(len(key) + len(value) for key, value in archive.items())
            <= 3000
        )


def test_terminal_write_rejects_oversize_without_changing_either_store() -> None:
    from onyx.chat.incognito_context import (
        append_incognito_message,
        save_incognito_response,
    )

    session_id = uuid4()
    append_incognito_message(session_id, UserMessage(content="question"))
    client = get_redis_client()
    before = client.get(_context_key(session_id))
    archive_key = f"incognito_ctx:{session_id}:agents"
    archive_before = _archive(archive_key)
    reply = _terminal_record(str(uuid4()), "x" * 4000)
    with patch("onyx.chat.incognito_context._MAX_CONTEXT_BYTES", 1000):
        with pytest.raises(ValueError, match="storage limit"):
            save_incognito_response(
                session_id,
                reply,
                {},
                message_id=1,
                messages=messages_from_items(reply.items),
            )
    assert client.get(_context_key(session_id)) == before
    assert _archive(archive_key) == archive_before


def test_terminal_write_retries_conflicts_without_losing_root_or_child_records() -> (
    None
):
    from threading import Barrier, Lock

    from onyx.chat import incognito_context
    from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor

    session_id = uuid4()
    root_id = str(uuid4())
    incognito_context.append_incognito_message(
        session_id, UserMessage(content="question")
    )
    barrier, lock = Barrier(2), Lock()
    queued = 0
    queue_write = incognito_context._queue_write

    def synchronize(
        pipeline: TenantRedisPipeline, session_id: UUID, state: _IncognitoWrite
    ) -> None:
        nonlocal queued
        with lock:
            queued += 1
            should_wait = queued <= 2
        if should_wait:
            barrier.wait(timeout=5)
        queue_write(pipeline, session_id, state)

    replies = [_terminal_record(root_id, "first"), _terminal_record(root_id, "second")]
    for reply in replies:
        reply.child_runs = [_terminal_record(str(uuid4()), f"child of {reply.run_id}")]
    with patch.object(incognito_context, "_queue_write", synchronize):
        with ContextThreadPoolExecutor(max_workers=2) as executor:
            tasks = [
                executor.submit(
                    lambda index=index, reply=reply: (
                        incognito_context.save_incognito_response(
                            session_id,
                            reply,
                            {},
                            message_id=index,
                            messages=messages_from_items(reply.items),
                        )
                    )
                )
                for index, reply in enumerate(replies, 1)
            ]
            for task in tasks:
                task.result(timeout=10)
    assert {
        message.text for message in load_incognito_context(session_id).messages
    } == {"question", "first", "second"}
    assert len(incognito_context._incognito_records(session_id, [2, 1])) == 2


def test_teardown_during_terminal_commit_cannot_restore_replay_state() -> None:
    from onyx.chat import incognito_context

    session_id = uuid4()
    incognito_context.append_incognito_message(
        session_id, UserMessage(content="question")
    )
    reply = _terminal_record(str(uuid4()), "answer")
    queue_write = incognito_context._queue_write

    def end_session(
        pipeline: TenantRedisPipeline, session_id: UUID, state: _IncognitoWrite
    ) -> None:
        teardown_incognito_session(session_id)
        queue_write(pipeline, session_id, state)

    with patch.object(incognito_context, "_queue_write", end_session):
        with pytest.raises(RuntimeError, match="session ended"):
            incognito_context.save_incognito_response(
                session_id,
                reply,
                {},
                message_id=1,
                messages=messages_from_items(reply.items),
            )
    assert get_redis_client().get(_context_key(session_id)) == b"tombstone"
    assert _archive(f"incognito_ctx:{session_id}:agents") == {}


def test_root_replay_is_stored_once_and_conflicting_retries_are_rejected() -> None:
    from onyx.chat.incognito_context import (
        append_incognito_message,
        get_or_create_incognito_root_id,
        load_incognito_agent_metadata,
        save_incognito_response,
    )

    session_id = uuid4()
    root_id = str(uuid4())
    append_incognito_message(session_id, UserMessage(content="question"))
    get_or_create_incognito_root_id(session_id, root_id)
    reply = _terminal_record(root_id, "accepted output " + "x" * 3000)
    messages = messages_from_items(reply.items)
    with patch("onyx.chat.incognito_context._MAX_CONTEXT_BYTES", 4096):
        save_incognito_response(session_id, reply, {}, message_id=1, messages=messages)
        before = get_redis_client().get(_context_key(session_id))
        archive = _archive(f"incognito_ctx:{session_id}:agents")
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
        assert _archive(f"incognito_ctx:{session_id}:agents") == archive
        assert b"accepted output" not in archive[b"1"]
        assert load_incognito_agent_metadata(session_id, [1]) == []
        context = load_incognito_context(session_id)
        assert context.previous_run_id == reply.run_id
        assert [message.text for message in context.messages] == [
            "question",
            messages[0].text,
        ]
        append_incognito_message(session_id, UserMessage(content="followup"))
        assert load_incognito_context(session_id).messages[-2].text == messages[0].text
