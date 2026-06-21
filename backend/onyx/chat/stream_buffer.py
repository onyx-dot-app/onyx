"""Transient cross-pod buffer of a chat run's outbound stream.

The run's writer appends the exact NDJSON lines the SSE endpoint sends, stored in
the shared cache as zlib-compressed, sequence-numbered chunks so any api-server
pod can replay and tail an in-flight run. The cache is the only coordination
channel available on every deployment flavor (Redis, or Postgres on lite).

Chunks can disappear before the meta says the stream is over (allkeys-lru
eviction, TTL expiry): readers must treat a missing chunk as a gap and fall back
to the DB-rendered message rather than replaying a broken sequence.
"""

import zlib
from uuid import UUID

from pydantic import BaseModel
from pydantic import ValidationError

from onyx.cache.interface import CacheBackend
from onyx.configs.chat_configs import CHAT_STREAM_BUFFER_DONE_TTL_S
from onyx.configs.chat_configs import CHAT_STREAM_BUFFER_MAX_BYTES
from onyx.configs.chat_configs import CHAT_STREAM_BUFFER_TTL_S
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PREFIX = "chatstream"
# Flush once this much uncompressed data is pending; the run's writer thread also
# flushes on every idle tick, so flush latency stays at the tick interval.
_FLUSH_THRESHOLD_BYTES = 32 * 1024


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


def _chunk_key(chat_session_id: UUID, run_id: int, chunk_n: int) -> str:
    return f"{_PREFIX}_{chat_session_id}_{run_id}:{chunk_n}"


def _meta_key(chat_session_id: UUID, run_id: int) -> str:
    return f"{_PREFIX}_{chat_session_id}_{run_id}:meta"


class StreamBufferWriter:
    """Append-only writer for one run. Errors never propagate into the stream
    path — a broken cache downgrades the run to non-resumable (truncated)."""

    def __init__(
        self,
        cache: CacheBackend,
        chat_session_id: UUID,
        run_id: int,
    ) -> None:
        self._cache = cache
        self._chat_session_id = chat_session_id
        self._run_id = run_id
        self._meta = StreamBufferMeta()
        self._pending: list[str] = []
        self._pending_bytes = 0
        self._compressed_total = 0

    @property
    def run_id(self) -> int:
        return self._run_id

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
                    self._run_id,
                    CHAT_STREAM_BUFFER_MAX_BYTES,
                )
                return
            self._cache.set(
                _chunk_key(self._chat_session_id, self._run_id, self._meta.chunk_count),
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
                self._run_id,
            )
            self._meta.truncated = True
            try:
                self._write_meta(CHAT_STREAM_BUFFER_TTL_S)
            except Exception:
                logger.exception(
                    "stream buffer meta update failed after flush error for session %s run %d",
                    self._chat_session_id,
                    self._run_id,
                )

    def mark_done(self) -> None:
        self.flush()
        if self._meta.done:
            return
        self._meta.done = True
        try:
            self._write_meta(CHAT_STREAM_BUFFER_DONE_TTL_S)
            for chunk_n in range(self._meta.chunk_count):
                self._cache.expire(
                    _chunk_key(self._chat_session_id, self._run_id, chunk_n),
                    CHAT_STREAM_BUFFER_DONE_TTL_S,
                )
        except Exception:
            logger.exception(
                "stream buffer done-marking failed for session %s run %d",
                self._chat_session_id,
                self._run_id,
            )

    def _write_meta(self, ttl: int) -> None:
        self._cache.set(
            _meta_key(self._chat_session_id, self._run_id),
            self._meta.model_dump_json(),
            ex=ttl,
        )


def has_stream_buffer(cache: CacheBackend, chat_session_id: UUID, run_id: int) -> bool:
    """O(1) existence probe — no chunk reads or decompression."""
    return cache.exists(_meta_key(chat_session_id, run_id))


def read_stream_chunks(
    cache: CacheBackend,
    chat_session_id: UUID,
    run_id: int,
    cursor: int,
    max_chunks: int | None = None,
) -> StreamChunkRead | None:
    """Read buffered stream blocks from ``cursor``. Returns None when no buffer
    exists for the run (never started, or fully expired). ``max_chunks`` bounds
    memory per call — a capped read may return ``done=True`` with chunks still
    pending, so callers must re-read until ``blocks`` comes back empty."""
    meta_raw = cache.get(_meta_key(chat_session_id, run_id))
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
            run_id,
        )
        return None

    blocks: list[str] = []
    chunk_n = cursor
    gap = meta.truncated
    while chunk_n < meta.chunk_count:
        if max_chunks is not None and len(blocks) >= max_chunks:
            break
        raw = cache.get(_chunk_key(chat_session_id, run_id, chunk_n))
        if raw is None or not isinstance(raw, bytes):
            gap = True
            break
        try:
            blocks.append(zlib.decompress(raw).decode("utf-8"))
        except (zlib.error, UnicodeDecodeError):
            logger.warning(
                "stream buffer chunk decode failed for session %s run %d chunk %d",
                chat_session_id,
                run_id,
                chunk_n,
            )
            gap = True
            break
        chunk_n += 1

    return StreamChunkRead(blocks=blocks, next_cursor=chunk_n, done=meta.done, gap=gap)
