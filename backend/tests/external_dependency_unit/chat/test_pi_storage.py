"""Redis checkpoint fences and bounded concurrent browser stream fanout."""

import asyncio
import json
import os
import zlib
from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from onyx.chat.pi.storage import (
    MAX_STATE_BYTES,
    TTL,
    StreamHub,
    append_packet,
    load_state,
    run_key,
    save_inputs,
    save_state,
    session_key,
    state_redis,
)


class SampleState(BaseModel):
    value: str


@pytest.fixture
def stored_input() -> Generator[tuple[UUID, str], None, None]:
    run_id, session_id = uuid4(), uuid4()
    key = run_key(run_id, "inputs")
    try:
        save_inputs(run_id, session_id, 1, SampleState(value="provider-secret-canary"))
        yield run_id, key
    finally:
        state_redis().delete(key, session_key(session_id))


def test_inputs_preserve_serialization_and_retention(
    stored_input: tuple[UUID, str],
) -> None:
    run_id, key = stored_input
    redis = state_redis()
    envelope = redis.get(key)
    assert isinstance(envelope, bytes)
    expected = SampleState(value="provider-secret-canary")
    assert SampleState.model_validate_json(zlib.decompress(envelope)) == expected
    assert load_state(run_id, "inputs", SampleState) == expected
    ttl = redis.ttl(key)
    assert isinstance(ttl, int)
    assert 0 < ttl <= TTL
    updated = SampleState(value="updated-secret")
    save_state(run_id, "inputs", updated)
    assert load_state(run_id, "inputs", SampleState) == updated


def test_oversize_inputs_are_rejected_before_storage() -> None:
    run_id, session_id = uuid4(), uuid4()
    with pytest.raises(ValueError, match="storage budget"):
        save_inputs(run_id, session_id, 1, SampleState(value="x" * MAX_STATE_BYTES))
    assert state_redis().exists(run_key(run_id, "inputs"), session_key(session_id)) == 0


def test_checkpoint_validation_does_not_expose_input_values(
    stored_input: tuple[UUID, str],
) -> None:
    class IncompatibleState(BaseModel):
        required: int

    run_id, _ = stored_input
    with pytest.raises(ValueError, match="^Invalid agent checkpoint$") as error:
        load_state(run_id, "inputs", IncompatibleState)
    assert "provider-secret-canary" not in str(error.value)
    assert error.value.__suppress_context__


def test_deleted_run_content_cannot_be_recreated_by_late_callback() -> None:
    run_id = uuid4()
    redis = state_redis()
    suffixes = ("inputs", "host", "projection", "result")
    keys = [run_key(run_id, suffix) for suffix in suffixes]
    try:
        save_state(run_id, "inputs", SampleState(value="authorized"))
        for suffix in suffixes[1:]:
            save_state(run_id, suffix, SampleState(value="before teardown"))
            assert load_state(run_id, suffix, SampleState) == SampleState(
                value="before teardown"
            )
        redis.delete(*keys)
        for suffix in suffixes[1:]:
            with pytest.raises(ValueError, match="no longer active"):
                save_state(run_id, suffix, SampleState(value="late sensitive content"))
        assert redis.exists(*keys) == 0
    finally:
        redis.delete(*keys)


def test_concurrent_stream_readers_share_bounded_redis_capacity() -> None:
    subscribers = int(os.environ.get("PI_STREAM_TEST_SUBSCRIBERS", "300"))
    prefix = f"pi-storage-test:{uuid4()}"
    keys = [f"{prefix}:{index}" for index in range(subscribers)]
    redis = state_redis()
    with redis.pipeline() as pipeline:
        for key in keys:
            pipeline.set(key + ":bytes", "0", ex=60)
        pipeline.execute()

    async def fanout() -> None:
        hub = StreamHub()
        hub.start()

        async def read(key: str) -> str:
            stream = hub.stream(key)
            try:
                async for block in stream:
                    if '"value"' in block:
                        return block
                raise AssertionError("Stream closed before delivery")
            finally:
                await stream.aclose()

        tasks = [asyncio.create_task(read(key)) for key in keys]
        try:
            await asyncio.sleep(0.1)
            for key in keys:
                append_packet(key, SampleState(value=key))
            responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
            assert [json.loads(response) for response in responses] == [
                {"value": key} for key in keys
            ]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await hub.close()
        assert not hub.listeners

    try:
        asyncio.run(fanout())
    finally:
        redis.delete(*(name for key in keys for name in (key, key + ":bytes")))
