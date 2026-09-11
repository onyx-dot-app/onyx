"""Redis checkpoint fences and bounded concurrent browser stream fanout."""

import asyncio
import json
import os
from uuid import uuid4

import pytest
from pydantic import BaseModel

from onyx.chat.pi.storage import (
    StreamHub,
    append_packet,
    load_state,
    run_key,
    save_state,
    state_redis,
)


class SampleState(BaseModel):
    value: str


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
