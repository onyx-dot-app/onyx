"""Doc-sync taskset cleanup on task revoke/expire (uses real Redis).

Regression: an expired doc-sync task fires `task_revoked`, not `task_postrun`, so its
id must be removed from the taskset by `app_base.on_task_revoked`. Otherwise the taskset
never empties, `monitor_document_sync_taskset` never resets the fence, and new doc-sync
generation is blocked until the 7-day fence TTL.
"""

from collections.abc import Generator
from types import SimpleNamespace
from uuid import uuid4

import pytest

from onyx.background.celery.apps.app_base import on_task_revoked
from onyx.background.celery.tasks.vespa.document_sync import DOCUMENT_SYNC_PREFIX
from onyx.background.celery.tasks.vespa.document_sync import DOCUMENT_SYNC_TASKSET_KEY
from onyx.background.celery.tasks.vespa.document_sync import get_document_sync_remaining
from onyx.background.celery.tasks.vespa.document_sync import is_document_sync_fenced
from onyx.background.celery.tasks.vespa.document_sync import reset_document_sync
from onyx.background.celery.tasks.vespa.document_sync import set_document_sync_fence
from onyx.background.celery.tasks.vespa.tasks import monitor_document_sync_taskset
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient
from shared_configs.configs import (
    POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE as TEST_TENANT_ID,
)


def _revoke_request(task_id: str, tenant_id: str = TEST_TENANT_ID) -> SimpleNamespace:
    """Mimic the celery Context the task_revoked signal delivers (has id + kwargs)."""
    return SimpleNamespace(id=task_id, kwargs={"tenant_id": tenant_id})


@pytest.fixture
def redis_client(
    tenant_context: None,  # noqa: ARG001
) -> Generator[TenantRedisClient, None, None]:
    r = get_redis_client(tenant_id=TEST_TENANT_ID)
    reset_document_sync(r)
    try:
        yield r
    finally:
        reset_document_sync(r)


def test_revoked_doc_sync_task_drains_taskset(redis_client: TenantRedisClient) -> None:
    task_id = f"{DOCUMENT_SYNC_PREFIX}_{uuid4()}"
    redis_client.sadd(DOCUMENT_SYNC_TASKSET_KEY, task_id)
    assert get_document_sync_remaining(redis_client) == 1

    on_task_revoked(request=_revoke_request(task_id))

    assert get_document_sync_remaining(redis_client) == 0


def test_revoked_non_doc_sync_task_ignored(redis_client: TenantRedisClient) -> None:
    doc_sync_id = f"{DOCUMENT_SYNC_PREFIX}_{uuid4()}"
    redis_client.sadd(DOCUMENT_SYNC_TASKSET_KEY, doc_sync_id)

    on_task_revoked(request=_revoke_request(f"connectordeletion_{uuid4()}"))

    # an unrelated revoke must not touch the doc-sync taskset
    assert get_document_sync_remaining(redis_client) == 1


def test_revoke_unwedges_fence_end_to_end(redis_client: TenantRedisClient) -> None:
    """The stranded id is what holds the fence up; draining it lets the monitor reset."""
    task_id = f"{DOCUMENT_SYNC_PREFIX}_{uuid4()}"
    redis_client.sadd(DOCUMENT_SYNC_TASKSET_KEY, task_id)
    set_document_sync_fence(redis_client, 1)
    assert is_document_sync_fenced(redis_client)

    # stranded id present -> monitor cannot reset the fence
    monitor_document_sync_taskset(redis_client)
    assert is_document_sync_fenced(redis_client)

    # revoke drains the id -> monitor now resets, unblocking new generation
    on_task_revoked(request=_revoke_request(task_id))
    monitor_document_sync_taskset(redis_client)
    assert not is_document_sync_fenced(redis_client)
