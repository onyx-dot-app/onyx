"""Durable dispatch intent with a replaceable Redis delivery queue."""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from bullmq import Job, Queue

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import release_processing_run
from onyx.chat.chat_state import ChatTurnSetup
from onyx.chat.models import AnswerStreamPart
from onyx.chat.pi.input_storage import save_run_inputs
from onyx.chat.pi.inputs import RunInputs
from onyx.chat.pi.storage import (
    append_packet,
    run_key,
    state_redis,
    stream_key,
)
from onyx.db.agent_runs import any_runs_exist, create_runs
from onyx.db.models import AgentRun
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def queue_url() -> str:
    return os.environ.get("ONYX_AGENT_REDIS_URL", "redis://127.0.0.1:6381/0")


async def enqueue(run_id: UUID) -> None:
    queue = Queue("onyx-agent", {"connection": queue_url()})
    try:
        # Reconciliation only submits durable queued rows. Retained failed deliveries
        # must be explicitly reprocessed: add() with the same ID only deduplicates.
        job = await Job.fromId(queue, str(run_id))
        if job is not None:
            state = await job.getState()
            if state in ("failed", "completed"):
                try:
                    # BullMQ atomically checks the terminal state before requeueing.
                    await job.retry(state)
                    return
                except TypeError as error:
                    # The pinned Python binding exposes Lua state conflicts as TypeError.
                    # Another delivery can complete again before we re-read its state.
                    if (
                        str(error)
                        == f"Job {run_id} is not in the state {state}.reprocessJob"
                    ):
                        return
                    if await Job.fromId(queue, str(run_id)) is not None:
                        raise
                    # Retention pruned the job between lookup and retry; add it below.
            elif state != "unknown":
                return
        await queue.add(
            "chat",
            {"runId": str(run_id), "tenantId": get_current_tenant_id()},
            {
                "jobId": str(run_id),
                "attempts": 1,
                "removeOnComplete": {"age": 3600, "count": 10000},
                "removeOnFail": {"age": 3600, "count": 10000},
            },
        )
    finally:
        await queue.close()


def prepare_dispatch(
    setup: ChatTurnSetup, user_id: UUID, packets: list[AnswerStreamPart]
) -> list[UUID]:
    runs = []
    prepared_ids: list[UUID] = []
    creating = False
    try:
        for index, message in enumerate(setup.reserved_messages):
            run_id = uuid4()
            prepared_ids.append(run_id)
            inputs = RunInputs.capture(setup, user_id, index)
            save_run_inputs(
                run_id, setup.chat_session_id, setup.processing_run_id, inputs
            )
            runs.append(
                AgentRun(
                    id=run_id,
                    chat_session_id=setup.chat_session_id,
                    message_id=message.id,
                    group_id=setup.processing_run_id,
                    model_index=index,
                    status="queued",
                    cancel_requested=False,
                    expires_at=datetime.now(timezone.utc)
                    + timedelta(
                        seconds=int(
                            os.environ.get("ONYX_AGENT_RUN_TIMEOUT_SECONDS", "1800")
                        )
                    ),
                )
            )
        key = stream_key(setup.chat_session_id, setup.processing_run_id)
        for packet in packets:
            append_packet(key, packet)
        # A committed queued row is the dispatch intent. Recovery retries only unclaimed rows.
        creating = True
        create_runs(runs)
        return [run.id for run in runs]
    except Exception:
        safe_to_release = True
        if creating:
            try:
                safe_to_release = not any_runs_exist(prepared_ids)
            except Exception:
                # A lost COMMIT acknowledgement can still mean durable queued rows exist.
                # Leave their fence and inputs intact until reconciliation can decide.
                safe_to_release = False
                logger.exception("Could not resolve failed agent dispatch transaction")
        if safe_to_release:
            try:
                release_processing_run(
                    setup.chat_session_id, get_cache_backend(), setup.processing_run_id
                )
            except Exception:
                logger.exception("Could not release rejected chat processing fence")
            try:
                keys = [run_key(run_id, "inputs") for run_id in prepared_ids]
                key = stream_key(setup.chat_session_id, setup.processing_run_id)
                state_redis().delete(*keys, key, key + ":bytes", key + ":gap")
            except Exception:
                logger.exception("Could not clear rejected chat transient state")
        raise
