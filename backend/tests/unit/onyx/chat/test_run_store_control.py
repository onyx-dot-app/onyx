"""Synchronous ownership checks reject expired leases and retry transient cache failures."""

import threading
from typing import Literal
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


@pytest.fixture
def ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock]:
    clock = Clock()
    monkeypatch.setattr(run_store, "time", clock)
    cache = MagicMock(spec=CacheBackend)
    cache.exists.return_value = False
    cache.renew_if_value.return_value = True
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
    cache.renew_if_value.side_effect = [ConnectionError("offline"), True]
    clock.now = 10
    store.poll_control()
    assert lease.error is None
    clock.now = 10.5
    store.poll_control()
    assert cache.renew_if_value.call_count == 1
    clock.now = 11
    store.poll_control()
    assert lease.refreshed == 11
    run.cancel.assert_not_called()


def test_confirmed_ownership_loss_cancels_without_retry(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, clock = ownership
    cache.renew_if_value.return_value = False
    clock.now = 10
    store.poll_control()
    assert lease.error is not None
    run.cancel.assert_called_once()
    assert cache.renew_if_value.call_count == 1


@pytest.mark.parametrize("operation", ["renewal", "stop"])
def test_slow_cache_response_cannot_revive_expired_ownership(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
    operation: Literal["renewal", "stop"],
) -> None:
    store, lease, run, cache, clock = ownership

    def renew(_key: str, _value: bytes, _ttl: int) -> bool:
        clock.now = 55
        return True

    def read_stop(_key: str) -> bool:
        clock.now = 55
        return False

    if operation == "renewal":
        cache.renew_if_value.side_effect = renew
        clock.now = 10
    else:
        cache.exists.side_effect = read_stop
    store.poll_control()
    assert isinstance(lease.error, TimeoutError)
    assert lease.refreshed == 0
    run.cancel.assert_called_once()
    reads = cache.exists.call_count
    renewals = cache.renew_if_value.call_count
    clock.now = 56
    store.poll_control()
    assert lease.refreshed == 0
    assert cache.exists.call_count == reads
    assert cache.renew_if_value.call_count == renewals


def test_renewal_ttl_starts_before_response_arrives(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, clock = ownership

    def renew(_key: str, _value: bytes, _ttl: int) -> bool:
        clock.now = 14
        return True

    cache.renew_if_value.side_effect = renew
    clock.now = 10
    store.poll_control()
    assert lease.refreshed == 10
    run.cancel.assert_not_called()


def test_stop_read_failure_retries_without_invalidating_lease(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, lease, run, cache, _ = ownership
    cache.exists.side_effect = [ConnectionError("offline"), True, False]
    store.poll_control()
    assert lease.error is None
    run.cancel.assert_not_called()
    store.poll_control()
    run.cancel.assert_called_once()


def test_root_and_child_control_calls_use_the_callers_thread(
    ownership: tuple[ChatRunStore, _OwnerLease, MagicMock, MagicMock, Clock],
) -> None:
    store, _, root, cache, clock = ownership
    child = MagicMock(spec=Run)
    child_lease = _OwnerLease(
        ResponseOwner(token=uuid4(), message_id=2, root_message_id=1)
    )
    store._leases["child"] = child_lease
    store._owned["child"] = _OwnedRun(child, child_lease)
    calling_thread = threading.current_thread()
    checks: list[str] = []
    renewals: list[str] = []

    def read_stop(key: str) -> bool:
        assert threading.current_thread() is calling_thread
        checks.append(key)
        return key == store._stop_key("child")

    def renew(key: str, _value: bytes, _ttl: int) -> bool:
        assert threading.current_thread() is calling_thread
        renewals.append(key)
        return True

    cache.exists.side_effect = read_stop
    cache.renew_if_value.side_effect = renew
    clock.now = 10
    store.poll_control()
    assert checks == [store._stop_key("run"), store._stop_key("child")]
    assert renewals == [store._owner_key("run"), store._owner_key("child")]
    root.cancel.assert_not_called()
    child.cancel.assert_called_once()
