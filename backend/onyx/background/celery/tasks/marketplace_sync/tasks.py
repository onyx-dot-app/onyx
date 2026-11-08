"""Dispatch only durable marketplace requests, including interrupted work."""

from functools import partial
from threading import BoundedSemaphore
from uuid import UUID

from celery import shared_task

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryQueues, OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.marketplace_sync import (
    MESSAGE_SECONDS,
    request_marketplace_sync,
    reserve_marketplace_dispatches,
)
from onyx.skills.sync import sync_marketplace
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_future

logger = setup_logger()
_LITE_SLOTS = BoundedSemaphore(4)


def enqueue_marketplace_sync(marketplace_id: UUID, *, tenant_id: str) -> None:
    """Call after authorization and commit. Persist intent before broker I/O."""
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        request_marketplace_sync(marketplace_id, session)
    _dispatch(tenant_id, marketplace_id)


def _dispatch(tenant_id: str, marketplace_id: UUID | None = None) -> None:
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        ids = reserve_marketplace_dispatches(session, marketplace_id)
    for identifier in ids:
        try:
            if DISABLE_VECTOR_DB:
                if not _LITE_SLOTS.acquire(blocking=False):
                    continue
                try:
                    start_thread_future(
                        partial(_run_lite, identifier, tenant_id),
                        name="marketplace-sync",
                    )
                except Exception:
                    _LITE_SLOTS.release()
                    raise
            else:
                from onyx.background.celery.versioned_apps.client import app

                app.send_task(
                    OnyxCeleryTask.SYNC_MARKETPLACE,
                    kwargs={"marketplace_id": str(identifier), "tenant_id": tenant_id},
                    queue=OnyxCeleryQueues.SANDBOX,
                    priority=OnyxCeleryPriority.LOW,
                    expires=MESSAGE_SECONDS,
                )
        except Exception:
            # The durable request survives; never log provider or broker bodies.
            logger.warning("Marketplace dispatch deferred to recovery: %s", identifier)


def _run_lite(marketplace_id: UUID, tenant_id: str) -> None:
    try:
        sync_marketplace_task.run(
            marketplace_id=str(marketplace_id), tenant_id=tenant_id
        )
    finally:
        _LITE_SLOTS.release()


@shared_task(name=OnyxCeleryTask.SYNC_MARKETPLACE, ignore_result=True)
def sync_marketplace_task(*, marketplace_id: str, tenant_id: str) -> None:
    try:
        sync_marketplace(UUID(marketplace_id), tenant_id, request_work=False)
    except Exception:
        logger.warning("Marketplace sync deferred or failed: %s", marketplace_id)


@shared_task(name=OnyxCeleryTask.RECOVER_MARKETPLACE_SYNCS, ignore_result=True)
def recover_marketplace_syncs(*, tenant_id: str) -> None:
    _dispatch(tenant_id)
