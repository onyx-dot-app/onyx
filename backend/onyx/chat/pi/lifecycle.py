"""API-local notification fanout and durable queue reconciliation."""

import asyncio
import os
from contextlib import suppress
from datetime import datetime, timezone
from functools import partial

from anyio import CapacityLimiter, to_thread
from fastapi import FastAPI

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import (
    release_processing_run,
)
from onyx.chat.models import StreamingError
from onyx.chat.pi.dispatch import enqueue
from onyx.chat.pi.runtime import finish
from onyx.chat.pi.storage import (
    StreamHub,
    append_packet,
    finish_stream,
    run_key,
    state_redis,
    stream_key,
)
from onyx.db import agent_runs
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.db.models import AgentRun
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


def _recover_finalizer(run: AgentRun) -> None:
    recovered = agent_runs.recover_stale_finish(run.id, run.updated_at)
    if recovered is None:
        return
    # Finalization can include committed message writes and external effects.
    # Close abandoned execution; never call the finalizer for a second time.
    state_redis().delete(
        run_key(run.id, "inputs"),
        run_key(run.id, "host"),
        run_key(run.id, "projection"),
    )


def _repair_stream_closures() -> None:
    for group in agent_runs.pending_stream_closures():
        key = stream_key(group.session_id, group.group_id)
        if group.interrupted and not state_redis().exists(key + ":done"):
            append_packet(
                key,
                StreamingError(
                    error="Agent execution was interrupted.",
                    error_code="AGENT_INTERRUPTED",
                    is_retryable=False,
                ),
            )
        cache = get_cache_backend()
        release_processing_run(group.session_id, cache, group.group_id)
        finish_stream(key, content_free=group.content_free)
        agent_runs.mark_group_stream_closed(group.session_id, group.group_id)


async def recover() -> None:
    while True:
        try:
            tenants = (
                await to_thread.run_sync(get_all_tenant_ids)
                if MULTI_TENANT
                else [POSTGRES_DEFAULT_SCHEMA]
            )
            for tenant in tenants:
                token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
                try:
                    runs = await to_thread.run_sync(agent_runs.recovery_candidates)
                    for run in runs:
                        if run.status == "finishing":
                            await to_thread.run_sync(_recover_finalizer, run)
                        elif (
                            run.status == "queued"
                            and not run.cancel_requested
                            and run.expires_at > datetime.now(timezone.utc)
                        ):
                            await enqueue(run.id)
                        else:
                            await to_thread.run_sync(
                                partial(
                                    finish,
                                    run.id,
                                    run.attempt_id,
                                    "cancelled"
                                    if run.cancel_requested
                                    else "interrupted",
                                    observed_updated_at=run.updated_at,
                                )
                            )
                    await to_thread.run_sync(_repair_stream_closures)
                except Exception:
                    logger.exception(
                        "Agent queue reconciliation failed for tenant %s", tenant
                    )
                finally:
                    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Agent queue reconciliation failed")
        await asyncio.sleep(15)


async def start(app: FastAPI) -> None:
    if not os.environ.get("ONYX_AGENT_SERVICE_TOKEN", "").strip():
        raise ValueError("ONYX_AGENT_SERVICE_TOKEN is required for Pi chat")
    run_timeout = int(os.environ.get("ONYX_AGENT_RUN_TIMEOUT_SECONDS", "1800"))
    if not 1 <= run_timeout <= 1800:
        raise ValueError("ONYX_AGENT_RUN_TIMEOUT_SECONDS must be between 1 and 1800")
    app.state.agent_tool_limiter = CapacityLimiter(
        int(os.environ.get("ONYX_AGENT_TOOL_CONCURRENCY", "16"))
    )
    app.state.agent_stream_hub = StreamHub()
    app.state.agent_stream_hub.start()
    app.state.agent_recovery = asyncio.create_task(recover())


async def stop(app: FastAPI) -> None:
    app.state.agent_recovery.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.agent_recovery
    await app.state.agent_stream_hub.close()
