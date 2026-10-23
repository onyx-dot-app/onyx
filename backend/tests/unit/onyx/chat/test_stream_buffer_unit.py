"""Regression coverage for the chat stream buffer: chunk sequencing and cursor
reads, compression roundtrip, size-cap truncation, the done marker's TTL switch,
and missing-chunk gaps surfacing as non-replayable instead of broken replays."""

import contextvars
import os
import zlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from onyx.agents.concurrency import EventDelivery
from onyx.agents.events import AgentEvent, AgentStartEvent
from onyx.chat import stream_buffer
from onyx.chat.chat_processing_checker import (
    ACTIVE_LEASE_SECONDS,
    ChatTurnAdmission,
    get_processing_stream_id,
    is_chat_session_processing,
)
from onyx.chat.models import StreamingError
from onyx.chat.stream_buffer import (
    ChatDelivery,
    StreamBufferMeta,
    StreamBufferWriter,
    _StreamStatus,
    read_stream_chunks,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    OverallStop,
    Packet,
)
from onyx.server.utils import get_json_line
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
    first = Packet(
        placement=Placement(turn_index=0), obj=OverallStop(stop_reason="first")
    )
    second = Packet(
        placement=Placement(turn_index=0), obj=OverallStop(stop_reason="second")
    )

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
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_write = executor.submit(
            contextvars.copy_context().run, lambda: delivery.publish(first)
        )
        try:
            assert first_entered.wait(2)
            second_write = executor.submit(
                contextvars.copy_context().run, publish_second
            )
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
    admission = ChatTurnAdmission(cache)
    admission.claim(session_id)
    admission.publish(_STREAM_ID)
    for key in cache.expiries:
        cache.expiries[key] = ACTIVE_LEASE_SECONDS - 20
    assert is_chat_session_processing(session_id, cache)
    assert get_processing_stream_id(session_id, cache) == _STREAM_ID
    admission.release()
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
        output.publish(
            Packet(
                placement=Placement(turn_index=0),
                obj=OverallStop(stop_reason=event.run_id),
            )
        )

    monkeypatch.setattr(cache, "set", write)
    channel.subscribe(receive)
    output.start()
    try:
        channel.publish(AgentStartEvent(run_id="first"))
        assert writing.wait(2)
        assert next(output.reader) == Packet(
            placement=Placement(turn_index=0), obj=OverallStop(stop_reason="first")
        )
        assert channel.tracker.wait_idle(timeout=0)
        # Cache I/O must not hold the publication lock used by execution/control.
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(
                contextvars.copy_context().run,
                lambda: output.publish(
                    Packet(
                        placement=Placement(turn_index=0),
                        obj=OverallStop(stop_reason="control"),
                    )
                ),
            ).result(timeout=1)
        channel.publish(AgentStartEvent(run_id="second"))
    finally:
        release.set()
        channel.close()
        output.finish()
    assert list(output.reader) == [
        Packet(
            placement=Placement(turn_index=0), obj=OverallStop(stop_reason="control")
        ),
        Packet(
            placement=Placement(turn_index=0), obj=OverallStop(stop_reason="second")
        ),
    ]
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done and not saved.gap
    assert len(workers) == 1
    assert get_ident() not in workers
    assert "".join(saved.blocks) == "".join(
        get_json_line(
            Packet(
                placement=Placement(turn_index=0), obj=OverallStop(stop_reason=reason)
            ).model_dump()
        )
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
        output.publish(
            Packet(
                placement=Placement(turn_index=0),
                obj=OverallStop(stop_reason=event.run_id),
            )
        )

    def finish() -> None:
        finishing.set()
        output.finish()

    channel.subscribe(receive)
    channel.publish(AgentStartEvent(run_id="first"))
    try:
        assert entered.wait(2)
        channel.publish(AgentStartEvent(run_id="second"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            closing = executor.submit(contextvars.copy_context().run, finish)
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
        Packet(placement=Placement(turn_index=0), obj=OverallStop(stop_reason=reason))
        for reason in ("first", "second")
    ]
    assert list(output.reader) == packets
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done and not saved.gap
    assert "".join(saved.blocks) == "".join(
        get_json_line(packet.model_dump()) for packet in packets
    )


@pytest.mark.parametrize("single_event", [False, True])
def test_packet_bursts_flush_full_batches_before_the_timer(
    monkeypatch: pytest.MonkeyPatch, single_event: bool
) -> None:
    monkeypatch.setattr("onyx.agents.concurrency.EVENT_FLUSH_INTERVAL_SECONDS", 60)
    monkeypatch.setattr(
        stream_buffer,
        "_REPLAY_BACKLOG_MAX_BYTES",
        stream_buffer._FLUSH_THRESHOLD_BYTES * 2,
    )
    cache = FakeCache()
    session_id = uuid4()
    output = ChatDelivery(_make_writer(cache, session_id))
    channel = EventDelivery(output.events)
    packets = [
        Packet(
            placement=Placement(turn_index=0, model_index=index % 2),
            obj=AgentResponseDelta(content=str(index)),
        )
        for index in range(1025)
    ]

    def receive(event: AgentEvent) -> None:
        for packet in packets if single_event else [packets[int(event.run_id)]]:
            output.publish(packet)

    channel.subscribe(receive)
    try:
        for index in range(1 if single_event else len(packets)):
            channel.publish(AgentStartEvent(run_id=str(index)))
        assert channel.tracker.wait_idle(timeout=5)
        buffered = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
        assert buffered is not None and buffered.blocks and not buffered.gap
    finally:
        channel.close()
        output.finish()
    assert list(output.reader) == packets
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done and not saved.gap
    assert "".join(saved.blocks) == "".join(
        get_json_line(packet.model_dump()) for packet in packets
    )


def test_pending_replay_retains_many_small_packets() -> None:
    cache = FakeCache()
    session_id = uuid4()
    output = ChatDelivery(_make_writer(cache, session_id))
    packets = [
        Packet(
            placement=Placement(turn_index=0),
            obj=AgentResponseDelta(content=str(index)),
        )
        for index in range(1025)
    ]
    for packet in packets:
        output.publish(packet)
    output.finish()

    assert list(output.reader) == packets
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done and not saved.gap
    assert "".join(saved.blocks) == "".join(
        get_json_line(packet.model_dump()) for packet in packets
    )


@pytest.mark.parametrize("overflow", [False, True])
def test_pending_replay_byte_limit_preserves_live_output(
    monkeypatch: pytest.MonkeyPatch, overflow: bool
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    output = ChatDelivery(_make_writer(cache, session_id))
    packet = Packet(
        placement=Placement(turn_index=0), obj=AgentResponseDelta(content="🙂")
    )
    line = get_json_line(packet.model_dump())
    monkeypatch.setattr(
        stream_buffer,
        "_REPLAY_BACKLOG_MAX_BYTES",
        len(line.encode("utf-8")) * 2 - (1 if overflow else 0),
    )
    output.publish(packet)
    output.publish(packet)
    output.finish()

    assert list(output.reader) == [packet, packet]
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done
    assert saved.gap == overflow
    if not overflow:
        assert "".join(saved.blocks) == line * 2


@pytest.mark.parametrize("cache_fails", [False, True])
@pytest.mark.parametrize("delete_on_done", [False, True])
def test_replay_failure_does_not_fail_live_output(
    monkeypatch: pytest.MonkeyPatch, cache_fails: bool, delete_on_done: bool
) -> None:
    cache = _FailingChunkCache() if cache_fails else FakeCache()
    if not cache_fails:
        monkeypatch.setattr(stream_buffer, "CHAT_STREAM_BUFFER_MAX_BYTES", 1)
    session_id = uuid4()
    output = ChatDelivery(
        StreamBufferWriter(cache, session_id, _STREAM_ID, delete_on_done=delete_on_done)
    )
    packet = Packet(placement=Placement(turn_index=0), obj=OverallStop())
    output.publish(packet)
    output.finish()
    assert list(output.reader) == [packet]
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    if delete_on_done:
        assert saved is None
        assert not cache.store
    else:
        assert saved is not None and saved.done and saved.gap


def test_replay_overflow_does_not_suppress_a_later_live_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    output = ChatDelivery(_make_writer(cache, session_id))
    packet = Packet(placement=Placement(turn_index=0), obj=OverallStop())
    monkeypatch.setattr(
        stream_buffer,
        "_REPLAY_BACKLOG_MAX_BYTES",
        len(get_json_line(packet.model_dump()).encode("utf-8")),
    )
    for _ in range(2):
        output.publish(packet)
        assert next(output.reader) == packet
    with patch("onyx.chat.stream_buffer.get_json_line") as serialize:
        output.publish(packet)
        serialize.assert_not_called()
    assert next(output.reader) == packet
    output.report_gap()
    output.report_gap()
    output.finish()
    remaining = list(output.reader)
    assert len(remaining) == 1
    assert isinstance(remaining[0], StreamingError)
    assert remaining[0].error_code == "STREAM_GAP"
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done and saved.gap


@pytest.mark.parametrize("periodic_flush", [False, True])
def test_cache_cleanup_timeout_does_not_fail_completed_live_output(
    monkeypatch: pytest.MonkeyPatch, periodic_flush: bool
) -> None:
    monkeypatch.setattr("onyx.agents.concurrency.CLEANUP_SECONDS", 0.01)
    cache = FakeCache()
    session_id = uuid4()
    output = ChatDelivery(_make_writer(cache, session_id))
    writing = Event()
    release = Event()
    set_cache = cache.set

    def write(
        key: str, value: str | bytes | int | float, ex: int | None = None
    ) -> None:
        writing.set()
        assert release.wait(5)
        set_cache(key, value, ex)

    monkeypatch.setattr(cache, "set", write)
    packet = Packet(placement=Placement(turn_index=0), obj=OverallStop())
    output.publish(packet)
    try:
        if periodic_flush:
            output.start()
            assert writing.wait(2)
        output.finish()
        assert writing.wait(2)
        assert not output.finished.done()
        assert list(output.reader) == [packet]
    finally:
        release.set()
        output.events.close()
        output.finished.result(timeout=3)
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done and not saved.gap


def test_event_delivery_timeout_reports_missing_live_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.agents.concurrency.CLEANUP_SECONDS", 0.01)
    cache = FakeCache()
    session_id = uuid4()
    output = ChatDelivery(_make_writer(cache, session_id))
    channel = EventDelivery(output.events)
    entered = Event()
    release = Event()

    def receive(_event: AgentEvent) -> None:
        entered.set()
        assert release.wait(5)
        output.publish(Packet(placement=Placement(turn_index=0), obj=OverallStop()))

    channel.subscribe(receive)
    channel.publish(AgentStartEvent(run_id="response"))
    try:
        assert entered.wait(2)
        output.finish()
        items = list(output.reader)
        assert len(items) == 1
        assert isinstance(items[0], StreamingError)
        assert items[0].error_code == "STREAM_GAP"
    finally:
        release.set()
        assert channel.tracker.wait_idle(timeout=3)
        channel.close()
        output.events.close()
        output.finished.result(timeout=3)
    saved = read_stream_chunks(cache, session_id, _STREAM_ID, cursor=0)
    assert saved is not None and saved.done and saved.gap
