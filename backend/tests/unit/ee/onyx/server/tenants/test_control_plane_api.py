"""Tests for the routes the control plane calls on the data plane."""

from datetime import datetime, timezone
from unittest.mock import patch

from ee.onyx.server.license.models import CustomerTier
from ee.onyx.server.tenants.control_plane_api import (
    push_usage_limit_overrides,
    update_tier,
)
from ee.onyx.server.tenants.models import (
    TierUpdateRequest,
    UsageLimitOverridesPushRequest,
)
from onyx.db.usage import UsageType


class TestUpdateTier:
    """Tests for the /tenants/tier-update receiver (control-plane -> data-plane)."""

    def _request(self) -> TierUpdateRequest:
        return TierUpdateRequest(
            tenant_id="tenant_abc",
            customer_tier=CustomerTier.BUSINESS,
            trial_end=None,
        )

    def test_invalidates_billing_cache_on_success(self) -> None:
        """A control-plane tier push must drop the cached billing/trial lookup so
        an upgrade takes effect without waiting on the TTL backstop."""
        with (
            patch(
                "ee.onyx.server.tenants.control_plane_api.update_tenant_tier"
            ) as mock_update,
            patch(
                "ee.onyx.server.tenants.control_plane_api.invalidate_billing_cache",
                return_value=True,
            ) as mock_invalidate,
        ):
            result = update_tier(self._request(), None)

        assert result.updated is True
        mock_update.assert_called_once()
        mock_invalidate.assert_called_once_with("tenant_abc")

    def test_skips_invalidation_when_tier_update_fails(self) -> None:
        """If the tier write fails the endpoint reports failure and must not
        invalidate the billing cache (nothing changed)."""
        with (
            patch(
                "ee.onyx.server.tenants.control_plane_api.update_tenant_tier",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "ee.onyx.server.tenants.control_plane_api.invalidate_billing_cache"
            ) as mock_invalidate,
        ):
            result = update_tier(self._request(), None)

        assert result.updated is False
        mock_invalidate.assert_not_called()

    def test_reports_failure_when_invalidation_fails(self) -> None:
        """A failed billing-cache drop must report updated=False so the control
        plane does not treat a still-stale cache as refreshed."""
        with (
            patch("ee.onyx.server.tenants.control_plane_api.update_tenant_tier"),
            patch(
                "ee.onyx.server.tenants.control_plane_api.invalidate_billing_cache",
                return_value=False,
            ) as mock_invalidate,
        ):
            result = update_tier(self._request(), None)

        assert result.updated is False
        mock_invalidate.assert_called_once()


class TestPushUsageLimitOverrides:
    """Tests for the /tenants/usage-limit-overrides receiver."""

    def _request(self) -> UsageLimitOverridesPushRequest:
        return UsageLimitOverridesPushRequest(
            tenant_id="tenant_abc",
            trial_start=datetime(2026, 11, 25, 14, 7, tzinfo=timezone.utc),
            limits={"llm_cost_cents": 10000},
        )

    def test_stores_the_state_on_the_playground(self) -> None:
        with (
            patch("ee.onyx.server.tenants.control_plane_api.IS_PLAYGROUND", True),
            patch(
                "ee.onyx.server.tenants.control_plane_api.store_tenant_usage_limit_state",
                return_value=True,
            ) as store,
        ):
            result = push_usage_limit_overrides(self._request(), None)

        assert result.updated is True
        tenant_id, state = store.call_args.args
        assert tenant_id == "tenant_abc"
        assert state.limits == {UsageType.LLM_COST: 10000}

    def test_refused_off_the_playground(self) -> None:
        with (
            patch("ee.onyx.server.tenants.control_plane_api.IS_PLAYGROUND", False),
            patch(
                "ee.onyx.server.tenants.control_plane_api.store_tenant_usage_limit_state"
            ) as store,
        ):
            result = push_usage_limit_overrides(self._request(), None)

        assert result.updated is False
        store.assert_not_called()

    def test_reports_a_failed_write_so_the_control_plane_retries(self) -> None:
        with (
            patch("ee.onyx.server.tenants.control_plane_api.IS_PLAYGROUND", True),
            patch(
                "ee.onyx.server.tenants.control_plane_api.store_tenant_usage_limit_state",
                return_value=False,
            ),
        ):
            result = push_usage_limit_overrides(self._request(), None)

        assert result.updated is False
