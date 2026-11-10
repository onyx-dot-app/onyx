"""Celery tasks for Firecracker sandbox VMs (`SANDBOX_RUNTIME=firecracker`)."""

import time
from datetime import datetime, timezone

from celery import shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CacheLock, CacheLockLostError
from onyx.configs.constants import OnyxCeleryTask, OnyxRedisLocks
from onyx.microvm.agent_client import HostAgentConfigError, MtlsHostAgentClientFactory
from onyx.microvm.configs import (
    FIRECRACKER_ENABLED,
    SANDBOX_FC_RECONCILE_INTERVAL_SECONDS,
)
from onyx.microvm.lifecycle import NoCheckpointSupport, UnknownActivity
from onyx.microvm.reconcile import reconcile_microvms

# A pass that runs longer than this ends; the next tick starts a new one.
RECONCILE_DEADLINE_SECONDS = max(60, 4 * SANDBOX_FC_RECONCILE_INTERVAL_SECONDS)
_LEASE_SECONDS = RECONCILE_DEADLINE_SECONDS + 30

# One process-wide pool of agent channels.
_client_factory = MtlsHostAgentClientFactory()


def _check_lease(lock: CacheLock, deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("microvm reconcile deadline exceeded")
    if not lock.owned():
        raise CacheLockLostError("microvm reconcile lease lost")
    lock.extend(_LEASE_SECONDS)


@shared_task(
    name=OnyxCeleryTask.MICROVM_RECONCILE,
    ignore_result=True,
)
def microvm_reconcile_task(*, tenant_id: str | None = None) -> None:  # noqa: ARG001
    """Compare every agent's VMs with the placement records (cluster-wide)."""
    if not FIRECRACKER_ENABLED:
        return
    lock = get_shared_cache_backend().lock(
        OnyxRedisLocks.MICROVM_RECONCILE_BEAT_LOCK, timeout=_LEASE_SECONDS
    )
    if not lock.acquire(blocking=False):
        task_logger.info("microvm_reconcile_task: lease held elsewhere, skipping")
        return
    deadline = time.monotonic() + RECONCILE_DEADLINE_SECONDS
    try:
        report = reconcile_microvms(
            get_shared_cache_backend(),
            _client_factory,
            # Until ENG-4580 and ENG-4575: never stop a VM automatically.
            NoCheckpointSupport(),
            UnknownActivity(),
            now=datetime.now(timezone.utc),
            check_lease=lambda: _check_lease(lock, deadline),
        )
    except HostAgentConfigError:
        task_logger.exception("microvm_reconcile_task: agent mTLS is not configured")
        return
    finally:
        if lock.owned():
            lock.release()
    if (
        report.adopted
        or report.cleared
        or report.orphans_marked
        or report.unreachable_nodes
        or report.failed
    ):
        task_logger.info(
            "microvm_reconcile_task nodes=%d unreachable=%s failed=%s adopted=%d "
            "cleared=%d orphans=%d stopped=%d slept=%d",
            report.nodes,
            report.unreachable_nodes,
            report.failed,
            len(report.adopted),
            len(report.cleared),
            len(report.orphans_marked),
            len(report.orphans_stopped),
            len(report.slept),
        )
