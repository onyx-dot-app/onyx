"""Regression coverage for the chat stream buffer: chunk sequencing and cursor
reads, compression roundtrip, size-cap truncation, the done marker's TTL switch,
and missing-chunk gaps surfacing as non-replayable instead of broken replays."""

import os
import zlib
from threading import Event, get_ident
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from onyx.agents.concurrency import EventDelivery
from onyx.agents.events import AgentEvent, AgentStartEvent
from onyx.chat import stream_buffer
from onyx.chat.chat_processing_checker import (
    FENCE_TTL,
    get_processing_stream_id,
    is_chat_session_processing,
    set_processing_status,
)
from onyx.chat.models import StreamingError
from onyx.chat.stream_buffer import (
    ChatDelivery,
    StreamBufferMeta,
    StreamBufferWriter,
    _StreamStatus,
    read_stream_chunks,
)
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet
from onyx.server.utils import get_json_line
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor
from tests.unit.fakes import FakeCache

_STREAM_ID = 42


def _make_writer(cache: FakeCache, session_id: UUID) -> StreamBufferWriter:
    return StreamBufferWriter(
        cache=cache, chat_session_id=session_id, stream_id=_STREAM_ID
    )


class _FailingChunkCache(FakeCache):
    """Simulates a cache that fails when storing chunk payloads but not meta."""

    def __init__(self) -> None:
        super().__init__()
        self._failed = False

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        if key.endswith(":meta"):
            super().set(key, value, ex)
            return
        if not self._failed and key.endswith(":0"):
            self._failed = True
            raise RuntimeError("simulated chunk write failure")
        super().set(key, value, ex)


def test_append_flush_and_cursor_read_roundtrip() -> None:
    cache = FakeCache()
    session_id = uuid4()
    writer = _make_writer(cache, session_id)

    writer.append_line('{"a": 1}\n')
    writer.append_line('{"b": 2}\n')
    writer.flush()
    writer.append_line('{"c": 3}\n')
    writer.flush()

    read = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert read is not None
    assert "".join(read.blocks) == '{"a": 1}\n{"b": 2}\n{"c": 3}\n'
    assert read.next_cursor == 2
    assert not read.done
    assert not read.gap

    # Cursor skips already-replayed chunks.
    later = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=1)
    assert later is not None
    assert "".join(later.blocks) == '{"c": 3}\n'
    assert later.next_cursor == 2


def test_chunks_are_compressed() -> None:
    cache = FakeCache()
    writer = _make_writer(cache, uuid4())
    line = '{"text": "' + "x" * 4096 + '"}\n'
    writer.append_line(line)
    writer.flush()

    chunk_key = next(k for k in cache.store if k.endswith(":0"))
    raw = cache.store[chunk_key]
    assert len(raw) < len(line)
    assert zlib.decompress(raw).decode("utf-8") == line


def test_no_buffer_returns_none() -> None:
    cache = FakeCache()
    assert read_stream_chunks(cache, uuid4(), 1, cursor=0) is None


def test_overflow_marks_truncated_and_stops_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stream_buffer, "CHAT_STREAM_BUFFER_MAX_BYTES", 64)
    cache = FakeCache()
    session_id = uuid4()
    writer = _make_writer(cache, session_id)

    # Incompressible payload exceeds the 64-byte compressed cap.
    writer.append_line(os.urandom(512).hex() + "\n")
    writer.flush()
    writer.append_line('{"after": "overflow"}\n')
    writer.flush()

    read = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert read is not None
    assert read.gap
    assert read.blocks == []


def test_mark_done_switches_ttls_and_sets_done() -> None:
    cache = FakeCache()
    session_id = uuid4()
    writer = _make_writer(cache, session_id)
    writer.append_line('{"a": 1}\n')
    writer.mark_done()

    read = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert read is not None
    assert read.done
    assert not read.gap
    assert "".join(read.blocks) == '{"a": 1}\n'
    # Every key dropped to the post-completion retention TTL.
    assert all(
        ttl == stream_buffer.CHAT_STREAM_BUFFER_DONE_TTL_S
        for ttl in cache.expiries.values()
    )

    # Idempotent; appends after done are ignored.
    writer.mark_done()
    writer.append_line('{"late": true}\n')
    writer.flush()
    meta = StreamBufferMeta.model_validate_json(
        cache.store[next(k for k in cache.store if k.endswith(":meta"))].decode()
    )
    assert meta.chunk_count == 1


def test_max_chunks_bounds_each_read() -> None:
    cache = FakeCache()
    session_id = uuid4()
    writer = _make_writer(cache, session_id)
    for i in range(3):
        writer.append_line(f'{{"n": {i}}}\n')
        writer.flush()
    writer.mark_done()

    first = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0, max_chunks=2)
    assert first is not None
    assert "".join(first.blocks) == '{"n": 0}\n{"n": 1}\n'
    assert first.next_cursor == 2
    assert not first.gap
    # done is reported even on a capped read; the empty follow-up read is the
    # caller's caught-up signal.
    assert first.done

    rest = read_stream_chunks(
        cache, session_id, _STREAM_ID, cursor=first.next_cursor, max_chunks=2
    )
    assert rest is not None
    assert "".join(rest.blocks) == '{"n": 2}\n'
    assert rest.next_cursor == 3

    empty = read_stream_chunks(
        cache, session_id, _STREAM_ID, cursor=rest.next_cursor, max_chunks=2
    )
    assert empty is not None
    assert empty.blocks == []
    assert empty.done


def test_missing_chunk_is_a_gap() -> None:
    cache = FakeCache()
    session_id = uuid4()
    writer = _make_writer(cache, session_id)
    writer.append_line('{"a": 1}\n')
    writer.flush()
    writer.append_line('{"b": 2}\n')
    writer.flush()

    # Simulate allkeys-lru evicting the first chunk.
    cache.delete(next(k for k in cache.store if k.endswith(":0")))

    read = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert read is not None
    assert read.gap
    assert read.blocks == []
    assert read.next_cursor == 0


def test_flush_failure_marks_truncated_and_persists_meta() -> None:
    cache = _FailingChunkCache()
    session_id = uuid4()
    writer = _make_writer(cache, session_id)

    writer.append_line('{"a": 1}\n')
    writer.flush()

    meta_key = f"chatstream_{session_id}_{_STREAM_ID}:meta"
    meta_raw = cache.store.get(meta_key)
    assert meta_raw is not None
    meta = StreamBufferMeta.model_validate_json(meta_raw.decode())
    assert meta.truncated
    assert meta.chunk_count == 0

    read = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert read is not None
    assert read.gap
    assert read.blocks == []


def test_corrupt_meta_reads_as_missing_buffer() -> None:
    cache = FakeCache()
    session_id = uuid4()
    cache.set(f"chatstream_{session_id}_{_STREAM_ID}:meta", b"not json{", ex=600)

    assert read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0) is None


def test_truncation_cache_failure_does_not_prevent_content_free_cleanup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = FakeCache()
    writer = StreamBufferWriter(
        cache=cache,
        chat_session_id=uuid4(),
        stream_id=_STREAM_ID,
        delete_on_done=True,
    )
    writer.append_line('{"text": "private"}\n')
    writer.flush()
    assert cache.store

    with patch.object(cache, "set", side_effect=RuntimeError("cache unavailable")):
        writer.mark_truncated()
        writer.mark_done()

    assert not cache.store
    assert "truncation update failed" in caplog.text


def test_concurrent_delivery_keeps_reader_and_cache_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    delivery = ChatDelivery(_make_writer(cache, session_id))
    first_entered = Event()
    release_first = Event()
    second_started = Event()
    publish = delivery.reader.publish
    first = Packet(obj=OverallStop(stop_reason="first"))
    second = Packet(obj=OverallStop(stop_reason="second"))

    def hold_first(item: Packet | StreamingError | _StreamStatus) -> None:
        publish(item)
        if item is first:
            first_entered.set()
            assert release_first.wait(2)

    def publish_second() -> None:
        second_started.set()
        delivery.publish(second)

    monkeypatch.setattr(delivery.reader, "publish", hold_first)
    delivery.start()
    with ContextThreadPoolExecutor(max_workers=2) as executor:
        first_write = executor.submit(lambda: delivery.publish(first))
        try:
            assert first_entered.wait(2)
            second_write = executor.submit(publish_second)
            assert second_started.wait(2)
            with pytest.raises(TimeoutError):
                second_write.result(timeout=0.05)
        finally:
            release_first.set()
        first_write.result(timeout=2)
        second_write.result(timeout=2)
    delivery.finish()
    delivery.publish(first)

    assert list(delivery.reader) == [first, second]
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None
    assert saved.done
    assert "".join(saved.blocks) == "".join(
        get_json_line(packet.model_dump()) for packet in (first, second)
    )


def test_delayed_refresh_does_not_mark_stream_inactive() -> None:
    cache = FakeCache()
    session_id = uuid4()
    set_processing_status(session_id, cache, True, stream_id=_STREAM_ID)
    for key in cache.expiries:
        cache.expiries[key] = FENCE_TTL - 120
    assert is_chat_session_processing(session_id, cache)
    assert get_processing_stream_id(session_id, cache) == _STREAM_ID
    set_processing_status(session_id, cache, False)
    assert not is_chat_session_processing(session_id, cache)


def test_event_delivery_and_cache_writes_share_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    output = ChatDelivery(_make_writer(cache, session_id))
    channel = EventDelivery(output.events)
    writing = Event()
    release = Event()
    workers: set[int] = set()
    set_cache = cache.set

    def write(
        key: str, value: str | bytes | int | float, ex: int | None = None
    ) -> None:
        workers.add(get_ident())
        writing.set()
        assert release.wait(3)
        set_cache(key, value, ex)

    def receive(event: AgentEvent) -> None:
        workers.add(get_ident())
        output.publish(Packet(obj=OverallStop(stop_reason=event.run_id)))

    monkeypatch.setattr(cache, "set", write)
    channel.subscribe(receive)
    output.start()
    try:
        channel.publish(AgentStartEvent(run_id="first"))
        assert writing.wait(2)
        assert next(output.reader) == Packet(obj=OverallStop(stop_reason="first"))
        assert channel.tracker.wait_idle(timeout=0)
        # Cache I/O must not hold the publication lock used by execution/control.
        with ContextThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(
                lambda: output.publish(Packet(obj=OverallStop(stop_reason="control")))
            ).result(timeout=1)
        channel.publish(AgentStartEvent(run_id="second"))
    finally:
        release.set()
        channel.close()
        output.finish()
    assert list(output.reader) == [
        Packet(obj=OverallStop(stop_reason="control")),
        Packet(obj=OverallStop(stop_reason="second")),
    ]
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done and not saved.gap
    assert len(workers) == 1
    assert get_ident() not in workers
    assert "".join(saved.blocks) == "".join(
        get_json_line(Packet(obj=OverallStop(stop_reason=reason)).model_dump())
        for reason in ("first", "control", "second")
    )


def test_delivery_finish_drains_accepted_agent_events() -> None:
    cache = FakeCache()
    session_id = uuid4()
    output = ChatDelivery(_make_writer(cache, session_id))
    channel = EventDelivery(output.events)
    entered = Event()
    release = Event()
    finishing = Event()

    def receive(event: AgentEvent) -> None:
        if event.run_id == "first":
            entered.set()
            assert release.wait(3)
        output.publish(Packet(obj=OverallStop(stop_reason=event.run_id)))

    def finish() -> None:
        finishing.set()
        output.finish()

    channel.subscribe(receive)
    channel.publish(AgentStartEvent(run_id="first"))
    try:
        assert entered.wait(2)
        channel.publish(AgentStartEvent(run_id="second"))
        with ContextThreadPoolExecutor(max_workers=1) as executor:
            closing = executor.submit(finish)
            try:
                assert finishing.wait(2)
                with pytest.raises(TimeoutError):
                    closing.result(timeout=0.05)
            finally:
                release.set()
            closing.result(timeout=2)
    finally:
        release.set()
        channel.close()
        output.finish()
    packets = [
        Packet(obj=OverallStop(stop_reason=reason)) for reason in ("first", "second")
    ]
    assert list(output.reader) == packets
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done and not saved.gap
    assert "".join(saved.blocks) == "".join(
        get_json_line(packet.model_dump()) for packet in packets
    )
