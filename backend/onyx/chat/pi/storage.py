"""Bounded transient state and replay. Redis notifications carry only stream keys."""

import asyncio
import json
import os
import zlib
from collections.abc import AsyncGenerator
from contextlib import suppress
from functools import lru_cache
from uuid import UUID

from pydantic import BaseModel
from redis import BlockingConnectionPool, Redis
from redis.asyncio import BlockingConnectionPool as AsyncBlockingConnectionPool
from redis.asyncio import Redis as AsyncRedis

from shared_configs.contextvars import get_current_tenant_id

TTL = 3600
MAX_STATE_BYTES = 32 * 1024 * 1024
MAX_STREAM_BYTES = 16 * 1024 * 1024
CHANNEL = "onyx-agent-wakeup"


def state_url() -> str:
    return os.environ.get("ONYX_AGENT_STATE_REDIS_URL", "redis://127.0.0.1:6379/0")


@lru_cache(maxsize=1)
def state_redis() -> Redis:
    return Redis.from_pool(
        BlockingConnectionPool.from_url(
            state_url(),
            max_connections=64,
            timeout=10,
            socket_timeout=10,
            socket_connect_timeout=5,
            password=os.environ.get("ONYX_AGENT_STATE_REDIS_PASSWORD"),
        )
    )


def run_key(run_id: UUID, suffix: str) -> str:
    return f"agent:{get_current_tenant_id()}:{run_id}:{suffix}"


def stream_key(session_id: UUID, group_id: int) -> str:
    return f"agent:{get_current_tenant_id()}:stream:{session_id}:{group_id}"


_SAVE_ACTIVE_STATE = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[2])
return 1
"""


def save_state(run_id: UUID, suffix: str, state: BaseModel) -> None:
    raw = state.model_dump_json().encode()
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("Agent context exceeds its storage budget")
    compressed = zlib.compress(raw)
    if suffix in {"host", "projection", "result"}:
        # Finalization and explicit teardown remove inputs and checkpoints in one
        # DEL. An in-flight callback must not recreate content after that fence.
        saved = state_redis().execute_command(
            "EVAL",
            _SAVE_ACTIVE_STATE,
            2,
            run_key(run_id, "inputs"),
            run_key(run_id, suffix),
            compressed,
            TTL,
        )
        if not saved:
            raise ValueError("Agent context is no longer active")
    else:
        state_redis().set(run_key(run_id, suffix), compressed, ex=TTL)


def load_state[Model: BaseModel](
    run_id: UUID, suffix: str, model: type[Model]
) -> Model:
    value = state_redis().get(run_key(run_id, suffix))
    if not isinstance(value, bytes):
        raise ValueError("Agent context expired; start a new run")
    return model.model_validate_json(zlib.decompress(value))


_APPEND = """
if redis.call('EXISTS', KEYS[1] .. ':done') == 1 then return 0 end
local bytes = tonumber(redis.call('GET', KEYS[1] .. ':bytes') or '0')
if bytes + string.len(ARGV[1]) > tonumber(ARGV[2]) then
  redis.call('SET', KEYS[1] .. ':gap', '1', 'EX', ARGV[3])
  redis.call('PUBLISH', ARGV[4], KEYS[1])
  return 0
end
redis.call('INCRBY', KEYS[1] .. ':bytes', string.len(ARGV[1]))
redis.call('EXPIRE', KEYS[1] .. ':bytes', ARGV[3])
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('PUBLISH', ARGV[4], KEYS[1])
return 1
"""


def append_packet(key: str, packet: BaseModel) -> None:
    state_redis().execute_command(
        "EVAL",
        _APPEND,
        1,
        key,
        packet.model_dump_json() + "\n",
        str(MAX_STREAM_BYTES),
        str(TTL),
        CHANNEL,
    )


def finish_stream(key: str, *, content_free: bool) -> None:
    redis = state_redis()
    with redis.pipeline() as pipe:
        pipe.set(key + ":done", "1", ex=TTL)
        # Give attached readers time to drain. Explicit session teardown deletes immediately.
        if content_free:
            pipe.expire(key, 30)
            pipe.expire(key + ":bytes", 30)
        pipe.publish(CHANNEL, key)
        pipe.execute()


class StreamHub:
    """One Pub/Sub connection per API process; idle clients hold no Redis connection."""

    def __init__(self) -> None:
        self.redis = AsyncRedis.from_pool(
            AsyncBlockingConnectionPool.from_url(
                state_url(),
                max_connections=64,
                timeout=10,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=10,
                password=os.environ.get("ONYX_AGENT_STATE_REDIS_PASSWORD"),
            )
        )
        self.listeners: dict[str, set[asyncio.Event]] = {}
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self.listen())

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        await self.redis.aclose()

    async def listen(self) -> None:
        while True:
            try:
                async with self.redis.pubsub() as pubsub:
                    await pubsub.subscribe(CHANNEL)
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            for event in self.listeners.get(message["data"], ()):
                                event.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Replay is authoritative; a missed notification only delays a reader.
                for events in self.listeners.values():
                    for event in events:
                        event.set()
                await asyncio.sleep(1)

    async def stream(self, key: str, cursor: int = 0) -> AsyncGenerator[str, None]:
        from onyx.server.query_and_chat.streaming_models import heartbeat_packet

        event = asyncio.Event()
        self.listeners.setdefault(key, set()).add(event)
        try:
            while True:
                event.clear()
                async with self.redis.pipeline(transaction=False) as pipe:
                    pipe.lrange(key, cursor, cursor + 127)
                    pipe.exists(key + ":done")
                    pipe.exists(key + ":gap")
                    pipe.exists(key + ":bytes")
                    blocks, done, gap, exists = await pipe.execute()
                if gap or (not exists and not done):
                    yield (
                        json.dumps(
                            {
                                "error": "Stream expired. Reload the conversation.",
                                "error_code": "STREAM_EXPIRED",
                                "is_retryable": False,
                            }
                        )
                        + "\n"
                    )
                    return
                if blocks:
                    cursor += len(blocks)
                    yield "".join(blocks)
                    continue
                if done:
                    return
                try:
                    await asyncio.wait_for(event.wait(), timeout=5)
                except TimeoutError:
                    yield heartbeat_packet().model_dump_json() + "\n"
        finally:
            self.listeners[key].discard(event)
            if not self.listeners[key]:
                del self.listeners[key]


def session_key(session_id: UUID) -> str:
    return f"agent:{get_current_tenant_id()}:session:{session_id}"


def save_inputs(
    run_id: UUID, session_id: UUID, group_id: int, inputs: BaseModel
) -> None:
    """Admission cannot recreate a session after its explicit teardown."""
    raw = inputs.model_dump_json().encode()
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("Agent context exceeds its storage budget")
    accepted = state_redis().execute_command(
        "EVAL",
        """
        if redis.call('EXISTS', KEYS[1] .. ':ended') == 1 then return 0 end
        redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[3])
        redis.call('SADD', KEYS[1], ARGV[2])
        redis.call('EXPIRE', KEYS[1], ARGV[3])
        return 1
    """,
        2,
        session_key(session_id),
        run_key(run_id, "inputs"),
        zlib.compress(raw),
        json.dumps({"run": str(run_id), "group": group_id}),
        str(TTL),
    )
    if accepted != 1:
        raise ValueError("Agent session has ended")
