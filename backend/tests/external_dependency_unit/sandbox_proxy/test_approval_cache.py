"""External-dependency-unit tests for `approval_cache` against a real
`CacheBackend` (Redis). Pins the RPUSH / BLPOP / TTL contract; mocks nothing."""

import threading
import time
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.cache.factory import get_cache_backend
from onyx.db.enums import ApprovalDecision
from onyx.sandbox_proxy import approval_cache as approval_cache_module
from onyx.sandbox_proxy.approval_cache import _wake_key
from onyx.sandbox_proxy.approval_cache import announce_approval
from onyx.sandbox_proxy.approval_cache import announce_key
from onyx.sandbox_proxy.approval_cache import cache_session_grant_actions
from onyx.sandbox_proxy.approval_cache import cached_session_grants_cover
from onyx.sandbox_proxy.approval_cache import pop_announcement
from onyx.sandbox_proxy.approval_cache import send_wake
from onyx.sandbox_proxy.approval_cache import wait_for_wake
from tests.external_dependency_unit.constants import TEST_TENANT_ID

# ---------------------------------------------------------------------------
# announce_approval / pop_announcement
# ---------------------------------------------------------------------------


def test_announce_then_pop_round_trip() -> None:
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    approval_id = uuid4()
    session_id = uuid4()

    announce_approval(approval_id, session_id, cache)
    popped = pop_announcement(session_id, timeout_s=1, cache=cache)

    assert popped == approval_id
    assert isinstance(popped, UUID)


def test_announce_applies_ttl() -> None:
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    session_id = uuid4()

    announce_approval(uuid4(), session_id, cache)
    remaining = cache.ttl(announce_key(session_id))

    # Hardcoded spec; test_approval_decision_values_complete pins the constant.
    assert 0 < remaining <= 60


def test_pop_announcement_timeout_returns_none() -> None:
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    assert pop_announcement(uuid4(), timeout_s=1, cache=cache) is None


def test_pop_announcement_unparseable_returns_none() -> None:
    """A malformed payload must not crash the merger thread."""
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    session_id = uuid4()

    cache.rpush(announce_key(session_id), b"not-a-uuid")
    assert pop_announcement(session_id, timeout_s=1, cache=cache) is None


# ---------------------------------------------------------------------------
# wait_for_wake / send_wake
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_wake_receives_send_wake() -> None:
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    approval_id = uuid4()

    def _produce() -> None:
        # Delay so the consumer is already parked on BLPOP.
        time.sleep(0.1)
        send_wake(approval_id, ApprovalDecision.APPROVED, cache)

    producer = threading.Thread(target=_produce)
    producer.start()
    try:
        decision = await wait_for_wake(approval_id, timeout_s=5, cache=cache)
    finally:
        producer.join()

    assert decision == ApprovalDecision.APPROVED


@pytest.mark.asyncio
async def test_wait_for_wake_timeout_returns_none() -> None:
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    decision = await wait_for_wake(uuid4(), timeout_s=1, cache=cache)
    assert decision is None


@pytest.mark.asyncio
async def test_wait_for_wake_unparseable_returns_none() -> None:
    """Pins the `except ValueError` branch in `wait_for_wake`."""
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    approval_id = uuid4()

    cache.rpush(_wake_key(approval_id), b"BANANA")
    decision = await wait_for_wake(approval_id, timeout_s=5, cache=cache)
    assert decision is None


def test_send_wake_applies_ttl() -> None:
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    approval_id = uuid4()

    send_wake(approval_id, ApprovalDecision.APPROVED, cache)
    remaining = cache.ttl(_wake_key(approval_id))

    # Hardcoded spec; the completeness check below pins the constant.
    assert 0 < remaining <= 30


# ---------------------------------------------------------------------------
# Session grants
# ---------------------------------------------------------------------------


def test_cached_session_grants_cover_requires_every_action() -> None:
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    session_id = uuid4()
    approval_id = uuid4()
    external_app_id = 42

    assert not cached_session_grants_cover(
        session_id=session_id,
        external_app_id=external_app_id,
        action_types=["slack.chat.post"],
        cache=cache,
    )

    cache_session_grant_actions(
        session_id=session_id,
        external_app_id=external_app_id,
        action_types=["slack.chat.post"],
        source_approval_id=approval_id,
        cache=cache,
    )

    assert cached_session_grants_cover(
        session_id=session_id,
        external_app_id=external_app_id,
        action_types=["slack.chat.post"],
        cache=cache,
    )
    assert not cached_session_grants_cover(
        session_id=session_id,
        external_app_id=external_app_id,
        action_types=["slack.chat.post", "slack.files.upload"],
        cache=cache,
    )
    assert not cached_session_grants_cover(
        session_id=session_id,
        external_app_id=external_app_id + 1,
        action_types=["slack.chat.post"],
        cache=cache,
    )


# ---------------------------------------------------------------------------
# Decision value encoding round-trip.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decision_value_round_trips() -> None:
    """Pins the enum → bytes → enum encoding; the completeness check below
    independently pins the full enum value set."""
    cache = get_cache_backend(tenant_id=TEST_TENANT_ID)
    approval_id = uuid4()

    send_wake(approval_id, ApprovalDecision.APPROVED, cache)
    received = await wait_for_wake(approval_id, timeout_s=5, cache=cache)

    assert received == ApprovalDecision.APPROVED


def test_approval_decision_values_complete() -> None:
    """Pins the full `ApprovalDecision` value set and the cache-layer TTL
    constants to their spec values (the TTL bound checks elsewhere hardcode
    the same specs)."""
    assert {d.value for d in ApprovalDecision} == {"APPROVED", "REJECTED", "EXPIRED"}
    assert approval_cache_module.ANNOUNCE_TTL_S == 60
    assert approval_cache_module.WAKE_TTL_S == 30
    assert approval_cache_module.WAIT_TIMEOUT_S == 180
