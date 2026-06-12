"""Regression coverage for the chat stream buffer: chunk sequencing and cursor
reads, compression roundtrip, size-cap truncation, the done marker's TTL switch,
and missing-chunk gaps surfacing as non-replayable instead of broken replays."""

import os
import zlib
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.chat import stream_buffer
from onyx.chat.stream_buffer import read_stream_chunks
from onyx.chat.stream_buffer import StreamBufferMeta
from onyx.chat.stream_buffer import StreamBufferWriter
from tests.unit.fakes import FakeCache

_RUN_ID = 42


def _make_writer(cache: FakeCache, session_id: UUID) -> StreamBufferWriter:
    return StreamBufferWriter(cache=cache, chat_session_id=session_id, run_id=_RUN_ID)


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

    read = read_stream_chunks(cache, session_id, _RUN_ID, cursor=0)
    assert read is not None
    assert "".join(read.blocks) == '{"a": 1}\n{"b": 2}\n{"c": 3}\n'
    assert read.next_cursor == 2
    assert not read.done
    assert not read.gap

    # Cursor skips already-replayed chunks.
    later = read_stream_chunks(cache, session_id, _RUN_ID, cursor=1)
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

    read = read_stream_chunks(cache, session_id, _RUN_ID, cursor=0)
    assert read is not None
    assert read.gap
    assert read.blocks == []


def test_mark_done_switches_ttls_and_sets_done() -> None:
    cache = FakeCache()
    session_id = uuid4()
    writer = _make_writer(cache, session_id)
    writer.append_line('{"a": 1}\n')
    writer.mark_done()

    read = read_stream_chunks(cache, session_id, _RUN_ID, cursor=0)
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

    first = read_stream_chunks(cache, session_id, _RUN_ID, cursor=0, max_chunks=2)
    assert first is not None
    assert "".join(first.blocks) == '{"n": 0}\n{"n": 1}\n'
    assert first.next_cursor == 2
    assert not first.gap
    # done is reported even on a capped read; the empty follow-up read is the
    # caller's caught-up signal.
    assert first.done

    rest = read_stream_chunks(
        cache, session_id, _RUN_ID, cursor=first.next_cursor, max_chunks=2
    )
    assert rest is not None
    assert "".join(rest.blocks) == '{"n": 2}\n'
    assert rest.next_cursor == 3

    empty = read_stream_chunks(
        cache, session_id, _RUN_ID, cursor=rest.next_cursor, max_chunks=2
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

    read = read_stream_chunks(cache, session_id, _RUN_ID, cursor=0)
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

    meta_key = f"chatstream_{session_id}_{_RUN_ID}:meta"
    meta_raw = cache.store.get(meta_key)
    assert meta_raw is not None
    meta = StreamBufferMeta.model_validate_json(meta_raw.decode())
    assert meta.truncated
    assert meta.chunk_count == 0

    read = read_stream_chunks(cache, session_id, _RUN_ID, cursor=0)
    assert read is not None
    assert read.gap
    assert read.blocks == []


def test_corrupt_meta_reads_as_missing_buffer() -> None:
    cache = FakeCache()
    session_id = uuid4()
    cache.set(f"chatstream_{session_id}_{_RUN_ID}:meta", b"not json{", ex=600)

    assert read_stream_chunks(cache, session_id, _RUN_ID, cursor=0) is None
