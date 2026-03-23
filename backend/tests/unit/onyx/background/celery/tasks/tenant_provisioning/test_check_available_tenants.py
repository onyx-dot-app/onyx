"""
Unit tests for the check_available_tenants task.

Tests verify:
- Provisioning loop calls pre_provision_tenant the correct number of times
- A failure in one provisioning call does not stop subsequent calls
- No provisioning happens when pool is already full
- TARGET_AVAILABLE_TENANTS is respected
"""

from unittest.mock import MagicMock

import pytest

from ee.onyx.background.celery.tasks.tenant_provisioning.tasks import (
    check_available_tenants,
)

# Access the underlying function directly, bypassing Celery's task wrapper
# which injects `self` as the first argument when bind=True.
_check_available_tenants = check_available_tenants.run


@pytest.fixture()
def _enable_multi_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.MULTI_TENANT",
        True,
    )


@pytest.fixture()
def mock_redis(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True

    mock_client = MagicMock()
    mock_client.lock.return_value = mock_lock

    monkeypatch.setattr(
        "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.get_redis_client",
        lambda tenant_id: mock_client,  # noqa: ARG005
    )
    return mock_client


@pytest.fixture()
def mock_pre_provision(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(
        "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.pre_provision_tenant",
        mock,
    )
    return mock


def _mock_available_count(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    """Set up the DB session mock to return a specific available tenant count."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.count.return_value = count

    monkeypatch.setattr(
        "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.get_session_with_shared_schema",
        lambda: mock_session,
    )


@pytest.mark.usefixtures("_enable_multi_tenant", "mock_redis")
class TestCheckAvailableTenants:
    def test_provisions_all_needed_tenants(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_pre_provision: MagicMock,
    ) -> None:
        """When pool has 2 and target is 5, should provision 3."""
        monkeypatch.setattr(
            "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.TARGET_AVAILABLE_TENANTS",
            5,
        )
        _mock_available_count(monkeypatch, 2)

        _check_available_tenants()

        assert mock_pre_provision.call_count == 3

    def test_provisions_from_empty_pool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_pre_provision: MagicMock,
    ) -> None:
        """When pool is empty, should provision the full target amount."""
        monkeypatch.setattr(
            "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.TARGET_AVAILABLE_TENANTS",
            20,
        )
        _mock_available_count(monkeypatch, 0)

        _check_available_tenants()

        assert mock_pre_provision.call_count == 20

    def test_no_provisioning_when_pool_full(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_pre_provision: MagicMock,
    ) -> None:
        """When pool already meets target, should not provision anything."""
        monkeypatch.setattr(
            "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.TARGET_AVAILABLE_TENANTS",
            5,
        )
        _mock_available_count(monkeypatch, 5)

        _check_available_tenants()

        assert mock_pre_provision.call_count == 0

    def test_no_provisioning_when_pool_exceeds_target(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_pre_provision: MagicMock,
    ) -> None:
        """When pool exceeds target, should not provision anything."""
        monkeypatch.setattr(
            "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.TARGET_AVAILABLE_TENANTS",
            5,
        )
        _mock_available_count(monkeypatch, 8)

        _check_available_tenants()

        assert mock_pre_provision.call_count == 0

    def test_failure_does_not_stop_remaining(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_pre_provision: MagicMock,
    ) -> None:
        """If one provisioning fails, the rest should still be attempted."""
        monkeypatch.setattr(
            "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.TARGET_AVAILABLE_TENANTS",
            5,
        )
        _mock_available_count(monkeypatch, 0)

        # Fail on calls 2 and 4 (0-indexed: 1 and 3)
        call_count = 0

        def side_effect() -> None:
            nonlocal call_count
            call_count += 1
            if call_count in (2, 4):
                raise RuntimeError("provisioning failed")

        mock_pre_provision.side_effect = side_effect

        _check_available_tenants()

        # All 5 should be attempted despite 2 failures
        assert mock_pre_provision.call_count == 5

    def test_skips_when_not_multi_tenant(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_pre_provision: MagicMock,
    ) -> None:
        """Should not provision when multi-tenancy is disabled."""
        monkeypatch.setattr(
            "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.MULTI_TENANT",
            False,
        )

        _check_available_tenants()

        assert mock_pre_provision.call_count == 0

    def test_skips_when_lock_not_acquired(
        self,
        mock_redis: MagicMock,
        mock_pre_provision: MagicMock,
    ) -> None:
        """Should skip when another instance holds the lock."""
        mock_redis.lock.return_value.acquire.return_value = False

        _check_available_tenants()

        assert mock_pre_provision.call_count == 0

    def test_lock_release_failure_does_not_raise(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_redis: MagicMock,
        mock_pre_provision: MagicMock,
    ) -> None:
        """LockNotOwnedError on release should be caught, not propagated."""
        from redis.exceptions import LockNotOwnedError

        monkeypatch.setattr(
            "ee.onyx.background.celery.tasks.tenant_provisioning.tasks.TARGET_AVAILABLE_TENANTS",
            5,
        )
        _mock_available_count(monkeypatch, 4)

        mock_redis.lock.return_value.release.side_effect = LockNotOwnedError("expired")

        # Should not raise
        _check_available_tenants()

        assert mock_pre_provision.call_count == 1
