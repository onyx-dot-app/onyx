"""Lease deadlines remain enforceable during cache failures and blocked I/O."""

from collections.abc import Callable
from concurrent.futures import Future
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.agents.runtime import Run
from onyx.cache.interface import CacheBackend
from onyx.chat import run_store
from onyx.chat.run_store import ChatRunStore, ResponseOwner, _OwnedRun, _OwnerLease


class Clock:
    now = 0.0

    def monotonic(self) -> float:
        return self.now


def completed[T](operation: Callable[[], T], **_kwargs: str) -> Future[T]:
    result: Future[T] = Future()
    try:
        result.set_result(operation())
    except Exception as error:
        result.set_exception(error)
    return result


@pytest.fixture
def ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock]:
    clock = Clock()
    monkeypatch.setattr(run_store, "time", clock)
    monkeypatch.setattr(run_store, "start_thread_future", completed)
    cache = MagicMock(spec=CacheBackend)
    cache.exists.return_value = False
    cache.expire_if_value.return_value = True
    store = ChatRunStore(
        tenant_id="tenant",
        chat_session_id=uuid4(),
        response_id=1,
        visible_response_ids=[],
        cache=cache,
        control_cache=cache,
    )
    lease = _OwnerLease(ResponseOwner(token=uuid4(), message_id=1, root_message_id=1))
    run = MagicMock(spec=Run)
    store._leases["run"] = lease
    store._owned["run"] = _OwnedRun(run, lease)
    return store, lease, run, cache, clock


def test_transient_renewal_failure_retries_without_cancelling(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, clock = ownership
    cache.expire_if_value.side_effect = [ConnectionError("offline"), True]
    clock.now = 10
    store.poll_control()
    store.poll_control()
    assert lease.error is None
    clock.now = 10.5
    store.poll_control()
    assert cache.expire_if_value.call_count == 1
    clock.now = 11
    store.poll_control()
    store.poll_control()
    assert lease.refreshed == 11
    run.cancel.assert_not_called()


def test_confirmed_ownership_loss_cancels_without_retry(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, clock = ownership
    cache.expire_if_value.return_value = False
    clock.now = 10
    store.poll_control()
    store.poll_control()
    assert lease.error is not None
    run.cancel.assert_called_once()
    assert cache.expire_if_value.call_count == 1


def test_blocked_renewal_and_stop_read_cannot_hide_expiry(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, lease, run, cache, clock = ownership
    renewal: Future[None] = Future()
    store._stop_check = Future()
    monkeypatch.setattr(
        run_store, "start_thread_future", lambda *_args, **_kwargs: renewal
    )
    clock.now = 10
    store.poll_control()
    clock.now = 54
    store.poll_control()
    run.cancel.assert_not_called()
    clock.now = 55
    store.poll_control()
    assert isinstance(lease.error, TimeoutError)
    run.cancel.assert_called_once()
    # A late successful response must not revive an abandoned owner.
    renewal.set_result(None)
    clock.now = 56
    store.poll_control()
    assert lease.refreshed == 0
    assert isinstance(lease.error, TimeoutError)
    cache.expire_if_value.assert_not_called()


def test_renewal_ttl_starts_before_response_arrives(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, _, clock = ownership
    clock.now = 10
    store.poll_control()
    clock.now = 14
    store.poll_control()
    assert lease.refreshed == 10
    run.cancel.assert_not_called()


def test_stop_read_failure_retries_without_invalidating_lease(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, _ = ownership
    cache.exists.side_effect = [ConnectionError("offline"), True, False]
    store.poll_control()
    store.poll_control()
    assert lease.error is None
    run.cancel.assert_not_called()
    store.poll_control()
    run.cancel.assert_called_once()
