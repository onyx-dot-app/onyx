"""Unit tests for cloud (multi-tenant) auto-bill seat enforcement.

Covers ``attempt_seat_billing_increase`` (Stripe error mapping +
idempotency) and ``enforce_cloud_seat_limit`` (trial bypass + decline
surfacing as ``OnyxError(SEAT_LIMIT_EXCEEDED)``).
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import stripe

from ee.onyx.server.tenants.billing import _seat_billing_idempotency_key
from ee.onyx.server.tenants.billing import attempt_seat_billing_increase
from ee.onyx.server.tenants.billing import enforce_cloud_seat_limit
from ee.onyx.server.tenants.billing import SeatBillingDeclineReason
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_BILLING = "ee.onyx.server.tenants.billing"


def _stripe_subscription(quantity: int) -> dict:
    return {
        "items": {
            "data": [
                {
                    "id": "si_123",
                    "price": MagicMock(id="price_123"),
                    "quantity": quantity,
                }
            ]
        }
    }


class TestIdempotencyKey:
    def test_stable_for_same_inputs(self) -> None:
        assert _seat_billing_idempotency_key("t1", 5) == _seat_billing_idempotency_key(
            "t1", 5
        )

    def test_differs_per_tenant(self) -> None:
        assert _seat_billing_idempotency_key("t1", 5) != _seat_billing_idempotency_key(
            "t2", 5
        )

    def test_differs_per_quantity(self) -> None:
        assert _seat_billing_idempotency_key("t1", 5) != _seat_billing_idempotency_key(
            "t1", 6
        )


class TestAttemptSeatBillingIncrease:
    @patch(f"{_BILLING}.register_tenant_users")
    @patch(f"{_BILLING}.stripe.Subscription.retrieve")
    @patch(f"{_BILLING}.fetch_tenant_stripe_information")
    def test_success_calls_register_with_target_and_idempotency_key(
        self,
        mock_fetch: MagicMock,
        mock_retrieve: MagicMock,
        mock_register: MagicMock,
    ) -> None:
        mock_fetch.return_value = {"stripe_subscription_id": "sub_123"}
        mock_retrieve.return_value = _stripe_subscription(quantity=3)

        success, reason = attempt_seat_billing_increase("tenant_a", target_quantity=5)

        assert (success, reason) == (True, None)
        mock_register.assert_called_once()
        kwargs = mock_register.call_args.kwargs
        args = mock_register.call_args.args
        assert args[0] == "tenant_a"
        assert args[1] == 5
        assert kwargs["idempotency_key"] == _seat_billing_idempotency_key("tenant_a", 5)

    @patch(f"{_BILLING}.register_tenant_users")
    @patch(f"{_BILLING}.stripe.Subscription.retrieve")
    @patch(f"{_BILLING}.fetch_tenant_stripe_information")
    def test_idempotent_when_already_at_or_above_target(
        self,
        mock_fetch: MagicMock,
        mock_retrieve: MagicMock,
        mock_register: MagicMock,
    ) -> None:
        mock_fetch.return_value = {"stripe_subscription_id": "sub_123"}
        mock_retrieve.return_value = _stripe_subscription(quantity=10)

        success, reason = attempt_seat_billing_increase("tenant_a", target_quantity=5)

        assert (success, reason) == (True, None)
        mock_register.assert_not_called()

    @patch(f"{_BILLING}.register_tenant_users")
    @patch(f"{_BILLING}.stripe.Subscription.retrieve")
    @patch(f"{_BILLING}.fetch_tenant_stripe_information")
    def test_card_declined_returns_card_declined(
        self,
        mock_fetch: MagicMock,
        mock_retrieve: MagicMock,
        mock_register: MagicMock,
    ) -> None:
        mock_fetch.return_value = {"stripe_subscription_id": "sub_123"}
        mock_retrieve.return_value = _stripe_subscription(quantity=3)
        mock_register.side_effect = stripe.CardError(
            "card declined", param="card", code="card_declined"
        )

        success, reason = attempt_seat_billing_increase("tenant_a", target_quantity=5)

        assert (success, reason) == (False, SeatBillingDeclineReason.CARD_DECLINED)

    @patch(f"{_BILLING}.register_tenant_users")
    @patch(f"{_BILLING}.stripe.Subscription.retrieve")
    @patch(f"{_BILLING}.fetch_tenant_stripe_information")
    def test_invalid_request_returns_subscription_invalid(
        self,
        mock_fetch: MagicMock,
        mock_retrieve: MagicMock,
        mock_register: MagicMock,
    ) -> None:
        mock_fetch.return_value = {"stripe_subscription_id": "sub_123"}
        mock_retrieve.return_value = _stripe_subscription(quantity=3)
        mock_register.side_effect = stripe.InvalidRequestError(
            "no such subscription", param="id"
        )

        success, reason = attempt_seat_billing_increase("tenant_a", target_quantity=5)

        assert (success, reason) == (
            False,
            SeatBillingDeclineReason.SUBSCRIPTION_INVALID,
        )

    @patch(f"{_BILLING}.fetch_tenant_stripe_information")
    def test_missing_subscription_returns_subscription_invalid(
        self,
        mock_fetch: MagicMock,
    ) -> None:
        mock_fetch.return_value = {"stripe_subscription_id": ""}

        success, reason = attempt_seat_billing_increase("tenant_a", target_quantity=5)

        assert (success, reason) == (
            False,
            SeatBillingDeclineReason.SUBSCRIPTION_INVALID,
        )


class TestEnforceCloudSeatLimit:
    @patch(f"{_BILLING}.is_tenant_on_trial_fn")
    def test_trial_tenant_short_circuits(
        self,
        mock_trial: MagicMock,
    ) -> None:
        mock_trial.return_value = True
        with patch(f"{_BILLING}.get_current_tenant_id", return_value="t1"):
            # Must not raise, must not call Stripe.
            enforce_cloud_seat_limit(seats_needed=1)

    @patch(f"{_BILLING}.acquire_seat_lock")
    @patch("ee.onyx.server.tenants.user_mapping.get_tenant_count")
    @patch(f"{_BILLING}.attempt_seat_billing_increase")
    @patch(f"{_BILLING}.is_tenant_on_trial_fn")
    @patch(f"{_BILLING}.get_current_tenant_id")
    def test_success_returns_silently(
        self,
        mock_tenant_id: MagicMock,
        mock_trial: MagicMock,
        mock_attempt: MagicMock,
        mock_count: MagicMock,
        mock_acquire_lock: MagicMock,
    ) -> None:
        mock_tenant_id.return_value = "t1"
        mock_trial.return_value = False
        mock_count.return_value = 4
        mock_attempt.return_value = (True, None)
        db_session = MagicMock()

        enforce_cloud_seat_limit(seats_needed=2, db_session=db_session)

        mock_attempt.assert_called_once_with("t1", 6)
        mock_acquire_lock.assert_called_once_with(db_session, "t1")

    @pytest.mark.parametrize(
        "reason,expected_in_message",
        [
            (SeatBillingDeclineReason.CARD_DECLINED, "payment method was declined"),
            (SeatBillingDeclineReason.SUBSCRIPTION_INVALID, "active subscription"),
        ],
    )
    @patch(f"{_BILLING}.acquire_seat_lock")
    @patch("ee.onyx.server.tenants.user_mapping.get_tenant_count")
    @patch(f"{_BILLING}.attempt_seat_billing_increase")
    @patch(f"{_BILLING}.is_tenant_on_trial_fn")
    @patch(f"{_BILLING}.get_current_tenant_id")
    def test_decline_raises_seat_limit_exceeded(
        self,
        mock_tenant_id: MagicMock,
        mock_trial: MagicMock,
        mock_attempt: MagicMock,
        mock_count: MagicMock,
        mock_acquire_lock: MagicMock,
        reason: str,
        expected_in_message: str,
    ) -> None:
        del mock_acquire_lock  # injected by @patch but not asserted on
        mock_tenant_id.return_value = "t1"
        mock_trial.return_value = False
        mock_count.return_value = 4
        mock_attempt.return_value = (False, reason)

        with pytest.raises(OnyxError) as exc:
            enforce_cloud_seat_limit(seats_needed=1, db_session=MagicMock())

        assert exc.value.error_code == OnyxErrorCode.SEAT_LIMIT_EXCEEDED
        assert expected_in_message in exc.value.detail

    @patch(f"{_BILLING}.acquire_seat_lock")
    @patch("ee.onyx.server.tenants.user_mapping.get_tenant_count")
    @patch(f"{_BILLING}.attempt_seat_billing_increase")
    @patch(f"{_BILLING}.is_tenant_on_trial_fn")
    @patch(f"{_BILLING}.get_current_tenant_id", return_value="ctx_var_tenant")
    def test_explicit_tenant_id_overrides_context_var(
        self,
        _mock_tenant_id: MagicMock,
        mock_trial: MagicMock,
        mock_attempt: MagicMock,
        mock_count: MagicMock,
        mock_acquire_lock: MagicMock,
    ) -> None:
        """Caller-supplied tenant_id must be billed, not the context var."""
        mock_trial.return_value = False
        mock_count.return_value = 0
        mock_attempt.return_value = (True, None)
        db_session = MagicMock()

        enforce_cloud_seat_limit(
            seats_needed=1, tenant_id="explicit_tenant", db_session=db_session
        )

        mock_trial.assert_called_once_with("explicit_tenant")
        mock_count.assert_called_once_with("explicit_tenant")
        mock_attempt.assert_called_once_with("explicit_tenant", 1)
        mock_acquire_lock.assert_called_once_with(db_session, "explicit_tenant")
