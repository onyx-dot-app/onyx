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

from onyx.cache.interface import CacheBackendType
from onyx.chat.incognito_context import (
    INCOGNITO_CONTEXT_TTL_SECONDS,
    IncognitoContext,
    _context_key,
    incognito_context_available,
    load_incognito_context,
    save_incognito_context,
    teardown_incognito_session,
)
from onyx.chat.models import ChatLoadedFile, ChatMessageSimple, ToolCallSimple
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType
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


def _message(
    text: str, message_type: MessageType = MessageType.USER
) -> ChatMessageSimple:
    return ChatMessageSimple(
        message=text, token_count=len(text), message_type=message_type
    )


def _save(
    chat_session_id: UUID, messages: list[ChatMessageSimple], version: int = 0
) -> bool:
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
    assert loaded.messages[0].message == "turn one"


def test_sequential_turns_chain_versions() -> None:
    session_id = uuid4()
    assert _save(session_id, [_message("one")], version=0)

    first = load_incognito_context(session_id)
    assert _save(session_id, first.messages + [_message("two")], first.version)

    second = load_incognito_context(session_id)
    assert second.version == 2
    assert [m.message for m in second.messages] == ["one", "two"]


def test_corrupt_value_degrades_and_is_overwritable() -> None:
    session_id = uuid4()
    get_redis_client().set(_context_key(session_id), b"not json at all")

    context = load_incognito_context(session_id)
    assert context.messages == []
    assert context.version == 0

    # The load/save pair recovers: expecting version 0 overwrites the garbage.
    assert _save(session_id, [_message("fresh start")], version=0)
    assert load_incognito_context(session_id).messages[0].message == "fresh start"


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
    message = ChatMessageSimple(
        message="see attached",
        token_count=100,
        message_type=MessageType.USER,
        image_files=[image],
        image_token_count=85,
    )

    assert _save(session_id, [message])
    (loaded,) = load_incognito_context(session_id).messages

    assert loaded.image_files is None
    assert loaded.image_token_count == 0
    assert loaded.message == "see attached"


def test_tool_calls_round_trip() -> None:
    """Assistant tool calls and tool responses are part of history and must
    survive storage intact."""
    session_id = uuid4()
    call = ChatMessageSimple(
        message="",
        token_count=12,
        message_type=MessageType.ASSISTANT,
        tool_calls=[
            ToolCallSimple(
                tool_call_id="call_1",
                tool_name="run_search",
                tool_arguments={"query": "churn", "limit": 5, "nested": {"a": [1]}},
                token_count=12,
            )
        ],
    )
    response = ChatMessageSimple(
        message="3 documents found",
        token_count=4,
        message_type=MessageType.TOOL_CALL_RESPONSE,
        tool_call_id="call_1",
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
    assert loaded[0].message == "m5"
    assert loaded[-1].message == "m204"


def test_byte_cap_drops_oldest_but_keeps_an_oversized_singleton() -> None:
    session_id = uuid4()
    big = "x" * 600_000
    oversized = "y" * 1_200_000

    assert _save(session_id, [_message(big), _message(big + "newer")])
    loaded = load_incognito_context(session_id).messages
    assert len(loaded) == 1
    assert loaded[0].message.endswith("newer")

    # One message alone over the cap is stored anyway: an empty save would
    # read as session-ended on the next turn.
    singleton_session = uuid4()
    assert _save(singleton_session, [_message(oversized)])
    assert len(load_incognito_context(singleton_session).messages) == 1


def test_availability_follows_the_cache_backend() -> None:
    """USAGE_ONLY content must never reach Postgres, so the Postgres cache
    backend (Lite) means the feature is absent."""
    with patch("onyx.chat.incognito_context.app_configs") as mock_configs:
        mock_configs.CACHE_BACKEND = CacheBackendType.REDIS
        assert incognito_context_available()
        mock_configs.CACHE_BACKEND = CacheBackendType.POSTGRES
        assert not incognito_context_available()
