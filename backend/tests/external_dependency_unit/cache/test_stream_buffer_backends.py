"""Stream-buffer behavior on the real cache backends: the chunk write/read
roundtrip, done-marking, and gap signaling must hold identically on Redis and
the Postgres (lite) backend."""

from uuid import uuid4

from onyx.cache.interface import CacheBackend
from onyx.chat.stream_buffer import _chunk_key
from onyx.chat.stream_buffer import read_stream_chunks
from onyx.chat.stream_buffer import StreamBufferWriter


def test_roundtrip_and_done(cache: CacheBackend) -> None:
    session_id = uuid4()
    writer = StreamBufferWriter(cache=cache, chat_session_id=session_id, run_id=7)
    writer.append_line('{"a": 1}\n')
    writer.flush()
    writer.append_line('{"b": 2}\n')
    writer.mark_done()

    read = read_stream_chunks(cache, session_id, 7, cursor=0)
    assert read is not None
    assert "".join(read.blocks) == '{"a": 1}\n{"b": 2}\n'
    assert read.done
    assert not read.gap

    tail = read_stream_chunks(cache, session_id, 7, cursor=read.next_cursor)
    assert tail is not None
    assert tail.blocks == []
    assert tail.done


def test_missing_chunk_is_gap(cache: CacheBackend) -> None:
    session_id = uuid4()
    writer = StreamBufferWriter(cache=cache, chat_session_id=session_id, run_id=8)
    writer.append_line('{"a": 1}\n')
    writer.flush()
    writer.append_line('{"b": 2}\n')
    writer.flush()

    # Simulate eviction of the first chunk.
    cache.delete(_chunk_key(session_id, 8, 0))

    read = read_stream_chunks(cache, session_id, 8, cursor=0)
    assert read is not None
    assert read.gap
    assert read.blocks == []


def test_missing_run_returns_none(cache: CacheBackend) -> None:
    assert read_stream_chunks(cache, uuid4(), 999, cursor=0) is None
