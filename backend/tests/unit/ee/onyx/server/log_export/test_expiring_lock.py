from ee.onyx.server.log_export.api import _ExpiringLock


def test_expiring_lock_ttl_steal_and_stale_release() -> None:
    now = [0.0]
    lock = _ExpiringLock(ttl_seconds=60.0, clock=lambda: now[0])

    first = lock.try_acquire()
    assert first is not None
    assert lock.try_acquire() is None

    # Expiry lets a new holder steal the hold.
    now[0] = 61.0
    second = lock.try_acquire()
    assert second is not None

    # The stale holder's release must not free the new hold.
    lock.release(first)
    assert lock.held()

    lock.release(second)
    assert not lock.held()
    # A duplicate release stays a no-op.
    lock.release(second)
    assert not lock.held()
