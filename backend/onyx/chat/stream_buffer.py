"""Deliver live chat packets and retain resumable chunks in the shared cache.

Missing chunks require fallback to persisted conversation history.
"""

import queue
import threading
import zlib
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ValidationError

from onyx.agents.concurrency import EventDispatcher
from onyx.cache.interface import CacheBackend
from onyx.chat.models import StreamingError
from onyx.configs.chat_configs import (
    CHAT_HEARTBEAT_INTERVAL_S,
    CHAT_STREAM_BUFFER_DONE_TTL_S,
    CHAT_STREAM_BUFFER_MAX_BYTES,
    CHAT_STREAM_BUFFER_TTL_S,
)
from onyx.server.query_and_chat.streaming_models import Packet, heartbeat_packet
from onyx.server.utils import get_json_line
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PREFIX = "chatstream"
# Idle flushes bound latency below the chunk-size threshold.
_FLUSH_THRESHOLD_BYTES = 32 * 1024
_STREAM_QUEUE_CAPACITY = 1024
_BUFFER_WORK_CAPACITY = 128


class StreamBufferMeta(BaseModel):
    chunk_count: int = 0
    done: bool = False
    truncated: bool = False


class StreamChunkRead(BaseModel):
    """One reader pass over the buffer. ``gap`` means the sequence is unrecoverable
    (evicted/truncated) and the caller must fall back to the persisted message."""

    blocks: list[str]
    next_cursor: int
    done: bool
    gap: bool


def _chunk_key(chat_session_id: UUID, processing_key: int, chunk_n: int) -> str:
    return f"{_PREFIX}_{chat_session_id}_{processing_key}:{chunk_n}"


def _meta_key(chat_session_id: UUID, processing_key: int) -> str:
    return f"{_PREFIX}_{chat_session_id}_{processing_key}:meta"


def stream_buffer_key_pattern(chat_session_id: UUID) -> str:
    """Glob matching every buffered chunk and meta key of the session's runs."""
    return f"{_PREFIX}_{chat_session_id}_*"


class StreamBufferWriter:
    """Append-only writer for one chat turn. Errors never propagate into the stream
    path — a broken cache downgrades the run to non-resumable (truncated)."""

    def __init__(
        self,
        cache: CacheBackend,
        chat_session_id: UUID,
        processing_key: int,
        delete_on_done: bool = False,
        session_ended: Callable[[], bool] | None = None,
    ) -> None:
        self._cache = cache
        self._chat_session_id = chat_session_id
        self._processing_key = processing_key
        # Content-free incognito runs: completion deletes the run's keys, so a
        # flush racing the session teardown still cleans itself up. Costs
        # post-completion resume.
        self._delete_on_done = delete_on_done
        # Teardown scans the session's keys once. Without this the run keeps
        # writing answer chunks behind it, which then live out the buffer TTL
        # if the run never reaches completion.
        self._session_ended = session_ended
        self._meta = StreamBufferMeta()
        self._pending: list[str] = []
        self._pending_bytes = 0
        self._compressed_total = 0

    @property
    def processing_key(self) -> int:
        return self._processing_key

    @property
    def truncated(self) -> bool:
        return self._meta.truncated

    def append_line(self, line: str) -> None:
        if self._meta.truncated or self._meta.done:
            return
        self._pending.append(line)
        self._pending_bytes += len(line)
        if self._pending_bytes >= _FLUSH_THRESHOLD_BYTES:
            self.flush()

    def flush(self) -> None:
        if not self._pending or self._meta.truncated or self._meta.done:
            return
        if self._session_ended is not None and self._session_ended():
            self._pending = []
            self._pending_bytes = 0
            self.mark_done()
            return
        payload = zlib.compress("".join(self._pending).encode("utf-8"))
        self._pending = []
        self._pending_bytes = 0
        try:
            if self._compressed_total + len(payload) > CHAT_STREAM_BUFFER_MAX_BYTES:
                self._meta.truncated = True
                self._write_meta(CHAT_STREAM_BUFFER_TTL_S)
                logger.warning(
                    "stream buffer for session %s run %d exceeded %d bytes; "
                    "marking truncated",
                    self._chat_session_id,
                    self._processing_key,
                    CHAT_STREAM_BUFFER_MAX_BYTES,
                )
                return
            self._cache.set(
                _chunk_key(
                    self._chat_session_id, self._processing_key, self._meta.chunk_count
                ),
                payload,
                ex=CHAT_STREAM_BUFFER_TTL_S,
            )
            self._compressed_total += len(payload)
            self._meta.chunk_count += 1
            self._write_meta(CHAT_STREAM_BUFFER_TTL_S)
        except Exception:
            logger.exception(
                "stream buffer flush failed for session %s run %d; "
                "run continues non-resumable",
                self._chat_session_id,
                self._processing_key,
            )
            self._meta.truncated = True
            try:
                self._write_meta(CHAT_STREAM_BUFFER_TTL_S)
            except Exception:
                logger.exception(
                    "stream buffer meta update failed after flush error for session %s run %d",
                    self._chat_session_id,
                    self._processing_key,
                )

    def mark_truncated(self) -> None:
        """Require persisted-history fallback when stream delivery loses data."""
        if self._meta.truncated:
            return
        self._meta.truncated = True
        self._pending.clear()
        self._pending_bytes = 0
        try:
            self._write_meta(CHAT_STREAM_BUFFER_TTL_S)
        except Exception:
            logger.exception(
                "stream buffer truncation update failed for session %s run %d",
                self._chat_session_id,
                self._processing_key,
            )

    def mark_done(self) -> None:
        if self._delete_on_done:
            if self._meta.done:
                return
            self._meta.done = True
            try:
                self._cache.delete(
                    _meta_key(self._chat_session_id, self._processing_key)
                )
                for chunk_n in range(self._meta.chunk_count):
                    self._cache.delete(
                        _chunk_key(self._chat_session_id, self._processing_key, chunk_n)
                    )
            except Exception:
                logger.exception(
                    "stream buffer deletion failed for session %s run %d",
                    self._chat_session_id,
                    self._processing_key,
                )
            return
        self.flush()
        if self._meta.done:
            return
        self._meta.done = True
        try:
            self._write_meta(CHAT_STREAM_BUFFER_DONE_TTL_S)
            for chunk_n in range(self._meta.chunk_count):
                self._cache.expire(
                    _chunk_key(self._chat_session_id, self._processing_key, chunk_n),
                    CHAT_STREAM_BUFFER_DONE_TTL_S,
                )
        except Exception:
            logger.exception(
                "stream buffer done-marking failed for session %s run %d",
                self._chat_session_id,
                self._processing_key,
            )

    def _write_meta(self, ttl: int) -> None:
        self._cache.set(
            _meta_key(self._chat_session_id, self._processing_key),
            self._meta.model_dump_json(),
            ex=ttl,
        )


def has_stream_buffer(
    cache: CacheBackend, chat_session_id: UUID, processing_key: int
) -> bool:
    """O(1) existence probe — no chunk reads or decompression."""
    return cache.exists(_meta_key(chat_session_id, processing_key))


def read_stream_chunks(
    cache: CacheBackend,
    chat_session_id: UUID,
    processing_key: int,
    cursor: int,
    max_chunks: int | None = None,
) -> StreamChunkRead | None:
    """Read buffered stream blocks from ``cursor``. Returns None when no buffer
    exists for the run (never started, or fully expired). ``max_chunks`` bounds
    memory per call — a capped read may return ``done=True`` with chunks still
    pending, so callers must re-read until ``blocks`` comes back empty."""
    meta_raw = cache.get(_meta_key(chat_session_id, processing_key))
    if meta_raw is None:
        return None
    try:
        meta = StreamBufferMeta.model_validate_json(
            meta_raw.decode("utf-8") if isinstance(meta_raw, bytes) else str(meta_raw)
        )
    except (ValidationError, UnicodeDecodeError):
        logger.warning(
            "stream buffer meta corrupt for session %s run %d; treating as missing",
            chat_session_id,
            processing_key,
        )
        return None

    blocks: list[str] = []
    chunk_n = cursor
    gap = meta.truncated
    while chunk_n < meta.chunk_count:
        if max_chunks is not None and len(blocks) >= max_chunks:
            break
        raw = cache.get(_chunk_key(chat_session_id, processing_key, chunk_n))
        if raw is None or not isinstance(raw, bytes):
            gap = True
            break
        try:
            blocks.append(zlib.decompress(raw).decode("utf-8"))
        except (zlib.error, UnicodeDecodeError):
            logger.warning(
                "stream buffer chunk decode failed for session %s run %d chunk %d",
                chat_session_id,
                processing_key,
                chunk_n,
            )
            gap = True
            break
        chunk_n += 1

    return StreamChunkRead(blocks=blocks, next_cursor=chunk_n, done=meta.done, gap=gap)


class _StreamStatus(str, Enum):
    DONE = "done"


class ChatStream(Iterator[Packet | StreamingError]):
    """A bounded reader whose closure leaves execution and cache delivery running."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Packet | StreamingError | _StreamStatus] = queue.Queue(
            _STREAM_QUEUE_CAPACITY
        )
        self._lock = threading.Lock()
        self._closed = False

    def publish(self, item: Packet | StreamingError | _StreamStatus) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                logger.warning("Chat reader fell behind; use persisted history")
                self._discard_pending()
                self._queue.put_nowait(_stream_gap())
                self._queue.put_nowait(_StreamStatus.DONE)
                self._closed = True

    def __next__(self) -> Packet | StreamingError:
        try:
            item = self._queue.get(timeout=CHAT_HEARTBEAT_INTERVAL_S)
        except queue.Empty:
            return heartbeat_packet()
        if item is _StreamStatus.DONE:
            self.close()
            raise StopIteration
        return item

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._discard_pending()
            self._queue.put_nowait(_StreamStatus.DONE)

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


def _stream_gap() -> StreamingError:
    return StreamingError(
        error="The live stream is incomplete. Reload this conversation.",
        error_code="STREAM_GAP",
        is_retryable=True,
    )


class ChatDelivery:
    """Deliver packets independently of execution, with bounded cache work and cleanup."""

    def __init__(self, buffer: StreamBufferWriter | None) -> None:
        self.reader = ChatStream()
        self.finished: Future[None] = Future()
        self._buffer = buffer
        self._lines: queue.Queue[str] = queue.Queue(_BUFFER_WORK_CAPACITY)
        self._finished = threading.Event()
        self._closing = False
        self._gap = threading.Event()
        self._publish_lock = threading.RLock()
        self.events = EventDispatcher(flush=self._flush)

    def start(self) -> None:
        self.events.start()

    def publish(self, item: Packet | StreamingError) -> None:
        line = get_json_line(item.model_dump()) if self._buffer is not None else None
        # Concurrent model writers must produce the same order in both destinations.
        with self._publish_lock:
            if self._finished.is_set():
                return
            self.reader.publish(item)
            if line is None or self._gap.is_set():
                return
            try:
                self._lines.put_nowait(line)
            except queue.Full:
                logger.warning("Chat cache delivery exceeded its backlog bound")
                self.report_gap()

    def report_gap(self) -> None:
        with self._publish_lock:
            if self._gap.is_set():
                return
            self._gap.set()
            self.reader.publish(_stream_gap())

    def finish(self) -> None:
        with self._publish_lock:
            if self._closing:
                return
            self._closing = True
        try:
            self.events.close()
        except Exception:
            logger.exception("Chat delivery could not finalize")
            self._finished.set()
            self.report_gap()
            if not self.finished.done():
                self.finished.set_result(None)
        if not self.finished.done():
            logger.warning("Chat cache delivery cleanup exceeded its wait bound")
            self.report_gap()
        self.reader.publish(_StreamStatus.DONE)

    def _flush(self, final: bool) -> None:
        if final:
            with self._publish_lock:
                self._finished.set()
        if self.finished.done():
            return
        buffer = self._buffer
        try:
            if buffer is not None:
                # Bound each batch so cache producers cannot starve agent events.
                for _ in range(_BUFFER_WORK_CAPACITY):
                    try:
                        line = self._lines.get_nowait()
                    except queue.Empty:
                        break
                    if not self._gap.is_set():
                        buffer.append_line(line)
                if self._gap.is_set() and not buffer.truncated:
                    buffer.mark_truncated()
                buffer.flush()
                if buffer.truncated:
                    self.report_gap()
        except Exception:
            logger.exception("Chat cache delivery failed")
            self.report_gap()
        if not final:
            return
        try:
            if buffer is not None:
                if self._gap.is_set() and not buffer.truncated:
                    buffer.mark_truncated()
                buffer.mark_done()
        except Exception:
            logger.exception("Chat cache delivery could not finalize")
            self.report_gap()
        finally:
            self.finished.set_result(None)
