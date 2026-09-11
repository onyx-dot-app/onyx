"""Explicit removal of transient agent content when a session ends."""

import json
from typing import cast
from uuid import UUID

from onyx.chat.pi.storage import (
    CHANNEL,
    TTL,
    run_key,
    session_key,
    state_redis,
    stream_key,
)
from onyx.db.agent_runs import cancel_session_runs, list_session_runs


def delete_session_state(session_id: UUID) -> None:
    cancel_session_runs(session_id)
    runs = list_session_runs(session_id)
    redis = state_redis()
    index = session_key(session_id)
    redis.set(index + ":ended", "1", ex=TTL)
    indexed = [json.loads(item) for item in cast(set[bytes], redis.smembers(index))]
    run_ids = {run.id for run in runs} | {UUID(item["run"]) for item in indexed}
    groups = {run.group_id for run in runs} | {int(item["group"]) for item in indexed}
    with redis.pipeline() as pipe:
        pipe.delete(index)
        for run_id in run_ids:
            # State writes require the inputs key; deleting it fences late snapshots.
            pipe.delete(
                *(
                    run_key(run_id, suffix)
                    for suffix in ("inputs", "host", "projection", "result")
                )
            )
        for group in groups:
            key = stream_key(session_id, group)
            pipe.delete(key, key + ":bytes", key + ":gap")
            pipe.set(key + ":done", "1", ex=TTL)
            pipe.publish(CHANNEL, key)
        pipe.execute()
