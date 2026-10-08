"""Guards the orphan-tag sweep against overlap: while another sweep for the
tenant holds the lock, a new caller skips instead of starting a second drain."""

from unittest.mock import patch

import pytest
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.pruning.tasks import sweep_orphan_tags
from onyx.configs.constants import OnyxRedisLocks
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient

DRAIN = "onyx.background.celery.tasks.pruning.tasks.delete_orphan_tags_batched"


@pytest.mark.usefixtures("tenant_context")
def test_sweep_skips_while_lock_is_held(db_session: Session) -> None:
    r: TenantRedisClient = get_redis_client()
    holder: RedisLock = r.lock(OnyxRedisLocks.ORPHAN_TAG_SWEEP_LOCK, timeout=30)
    assert holder.acquire(blocking=False)
    try:
        with patch(DRAIN) as drain:
            sweep_orphan_tags(r, db_session)
        drain.assert_not_called()
    finally:
        holder.release()


@pytest.mark.usefixtures("tenant_context")
def test_sweep_drains_and_releases_lock(db_session: Session) -> None:
    r: TenantRedisClient = get_redis_client()
    r.delete(OnyxRedisLocks.ORPHAN_TAG_SWEEP_LOCK)

    with patch(DRAIN) as drain:
        sweep_orphan_tags(r, db_session)

    drain.assert_called_once_with(db_session)
    assert not r.exists(OnyxRedisLocks.ORPHAN_TAG_SWEEP_LOCK)


@pytest.mark.usefixtures("tenant_context")
def test_failed_drain_raises_and_releases_lock(db_session: Session) -> None:
    r: TenantRedisClient = get_redis_client()
    r.delete(OnyxRedisLocks.ORPHAN_TAG_SWEEP_LOCK)

    with patch(DRAIN, side_effect=RuntimeError("drain failed")):
        with pytest.raises(RuntimeError, match="drain failed"):
            sweep_orphan_tags(r, db_session)

    assert not r.exists(OnyxRedisLocks.ORPHAN_TAG_SWEEP_LOCK)
