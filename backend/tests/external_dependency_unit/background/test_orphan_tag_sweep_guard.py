"""Guards the orphan-tag sweep against overlap: while another sweep for the
tenant holds the lock, a new caller skips and leaves a pending flag that the
running sweep drains before it releases the lock."""

from unittest.mock import patch

import pytest
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.pruning.tasks import sweep_orphan_tags
from onyx.configs.constants import OnyxRedisLocks, OnyxRedisSignals
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient

DRAIN = "onyx.background.celery.tasks.pruning.tasks.delete_orphan_tags_batched"
LOCK = OnyxRedisLocks.ORPHAN_TAG_SWEEP_LOCK
PENDING = OnyxRedisSignals.ORPHAN_TAG_SWEEP_PENDING


@pytest.fixture
def r() -> TenantRedisClient:
    client: TenantRedisClient = get_redis_client()
    client.delete(LOCK, PENDING)
    return client


@pytest.mark.usefixtures("tenant_context")
def test_sweep_skips_and_flags_pending_while_lock_is_held(
    db_session: Session, r: TenantRedisClient
) -> None:
    holder: RedisLock = r.lock(LOCK, timeout=30)
    assert holder.acquire(blocking=False)
    try:
        with patch(DRAIN) as drain:
            sweep_orphan_tags(r, db_session)
        drain.assert_not_called()
        assert r.exists(PENDING)
    finally:
        holder.release()


@pytest.mark.usefixtures("tenant_context")
def test_sweep_drains_and_releases_lock(
    db_session: Session, r: TenantRedisClient
) -> None:
    with patch(DRAIN) as drain:
        sweep_orphan_tags(r, db_session)

    drain.assert_called_once_with(db_session)
    assert not r.exists(LOCK)


@pytest.mark.usefixtures("tenant_context")
def test_sweep_drains_again_when_a_skip_lands_mid_drain(
    db_session: Session, r: TenantRedisClient
) -> None:
    def drain_then_flag(_session: Session) -> int:
        # The first drain sees a skip arrive after its last query.
        if drain.call_count == 1:
            r.set(PENDING, 1)
        return 0

    with patch(DRAIN, side_effect=drain_then_flag) as drain:
        sweep_orphan_tags(r, db_session)

    assert drain.call_count == 2
    assert not r.exists(PENDING)
    assert not r.exists(LOCK)


@pytest.mark.usefixtures("tenant_context")
def test_failed_drain_raises_and_releases_lock(
    db_session: Session, r: TenantRedisClient
) -> None:
    with patch(DRAIN, side_effect=RuntimeError("drain failed")):
        with pytest.raises(RuntimeError, match="drain failed"):
            sweep_orphan_tags(r, db_session)

    assert not r.exists(LOCK)
