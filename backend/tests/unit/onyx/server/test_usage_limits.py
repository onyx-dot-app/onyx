"""Unit tests for the usage limit registry, the cloud policies and enforcement."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.db.usage import UsageLimitExceededError, UsageType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server import usage_limits
from onyx.server.tenant_usage_limits import TenantUsageLimitOverrides
from onyx.server.usage_limits import (
    CALENDAR_WEEK,
    CLOUD_PAID,
    CLOUD_TRIAL,
    NO_LIMIT,
    Allowance,
    LimitMeasure,
    LimitPolicy,
    LimitPolicyName,
    LimitScope,
    LimitWindow,
    WindowAnchor,
    check_llm_cost_limit_for_provider,
    check_usage_and_raise,
    get_limit_for_usage_type,
    policy_for_plan,
)

_TENANT = "tenant_test"


class TestPolicies:
    @pytest.mark.parametrize(
        "policy", [CLOUD_TRIAL, CLOUD_PAID], ids=lambda p: p.name.value
    )
    def test_cloud_policies_cover_every_type_as_weekly_tenant_counters(
        self, policy: LimitPolicy
    ) -> None:
        for usage_type in UsageType:
            allowance = policy.allowances[usage_type]
            assert allowance.scope == LimitScope.TENANT
            assert allowance.measure == LimitMeasure.COUNTER
            assert allowance.window == CALENDAR_WEEK
            assert allowance.override_field is not None

    def test_override_fields_name_the_plan(self) -> None:
        for usage_type in UsageType:
            trial = CLOUD_TRIAL.allowances[usage_type].override_field
            paid = CLOUD_PAID.allowances[usage_type].override_field
            assert trial is not None and trial.value.endswith("_trial")
            assert paid is not None and paid.value.endswith("_paid")

    def test_every_policy_name_has_one_policy(self) -> None:
        assert {CLOUD_TRIAL.name, CLOUD_PAID.name} == set(LimitPolicyName)

    def test_plan_selects_policy(self) -> None:
        assert policy_for_plan(True) is CLOUD_TRIAL
        assert policy_for_plan(False) is CLOUD_PAID

    def test_calendar_window_without_length_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="needs a length"):
            LimitWindow(anchor=WindowAnchor.CALENDAR)

    def test_counter_without_window_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="needs a window"):
            Allowance(limit=100)


class TestGetLimitForUsageType:
    def test_policy_amount_when_no_override(self) -> None:
        with patch.object(usage_limits, "_get_tenant_override", return_value=None):
            assert (
                get_limit_for_usage_type(UsageType.LLM_COST, True, _TENANT)
                == CLOUD_TRIAL.allowances[UsageType.LLM_COST].limit
            )
            assert (
                get_limit_for_usage_type(UsageType.LLM_COST, False, _TENANT)
                == CLOUD_PAID.allowances[UsageType.LLM_COST].limit
            )

    def test_override_replaces_the_policy_amount(self) -> None:
        overrides = TenantUsageLimitOverrides(
            tenant_id=_TENANT, llm_cost_cents_trial=5000
        )
        with patch.object(
            usage_limits,
            "fetch_versioned_implementation",
            return_value=lambda _tenant_id: overrides,
        ):
            # Trial field set: the override is the new total, not an addition.
            assert get_limit_for_usage_type(UsageType.LLM_COST, True, _TENANT) == 5000
            # Paid field unset: the paid policy still applies.
            assert (
                get_limit_for_usage_type(UsageType.LLM_COST, False, _TENANT)
                == CLOUD_PAID.allowances[UsageType.LLM_COST].limit
            )

    def test_override_can_lift_the_limit(self) -> None:
        with patch.object(usage_limits, "_get_tenant_override", return_value=NO_LIMIT):
            assert (
                get_limit_for_usage_type(UsageType.CHUNKS_INDEXED, True, _TENANT)
                == NO_LIMIT
            )

    def test_type_without_allowance_is_unlimited(self) -> None:
        empty = LimitPolicy(name=LimitPolicyName.CLOUD_TRIAL, allowances={})
        with (
            patch.object(usage_limits, "policy_for_plan", return_value=empty),
            patch.object(usage_limits, "_get_tenant_override") as lookup,
        ):
            assert (
                get_limit_for_usage_type(UsageType.LLM_COST, True, _TENANT) == NO_LIMIT
            )
            lookup.assert_not_called()

    def test_no_tenant_means_policy_amount_without_lookup(self) -> None:
        with patch.object(usage_limits, "_get_tenant_override") as lookup:
            get_limit_for_usage_type(UsageType.API_CALLS, True, None)
            lookup.assert_not_called()

    def test_failed_override_lookup_falls_back_to_policy(self) -> None:
        with patch.object(
            usage_limits,
            "fetch_versioned_implementation",
            side_effect=RuntimeError("control plane down"),
        ):
            assert (
                get_limit_for_usage_type(UsageType.API_CALLS, False, _TENANT)
                == CLOUD_PAID.allowances[UsageType.API_CALLS].limit
            )


def _over(usage_type: UsageType, current: float, limit: float) -> MagicMock:
    return MagicMock(side_effect=UsageLimitExceededError(usage_type, current, limit))


class TestCheckUsageAndRaise:
    def test_disabled_does_nothing(self) -> None:
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", False),
            patch.object(usage_limits, "is_tenant_on_trial_fn") as trial,
        ):
            check_usage_and_raise(MagicMock(), UsageType.LLM_COST, _TENANT)
            trial.assert_not_called()

    def test_type_the_policy_does_not_list_is_not_checked(self) -> None:
        empty = LimitPolicy(name=LimitPolicyName.CLOUD_TRIAL, allowances={})
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
            patch.object(usage_limits, "is_tenant_on_trial_fn", return_value=True),
            patch.object(usage_limits, "policy_for_plan", return_value=empty),
            patch.object(usage_limits, "check_usage_limit") as read,
        ):
            check_usage_and_raise(MagicMock(), UsageType.LLM_COST, _TENANT)
            read.assert_not_called()

    def test_unlimited_skips_the_usage_read(self) -> None:
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
            patch.object(usage_limits, "is_tenant_on_trial_fn", return_value=True),
            patch.object(
                usage_limits, "get_limit_for_usage_type", return_value=NO_LIMIT
            ),
            patch.object(usage_limits, "check_usage_limit") as read,
        ):
            check_usage_and_raise(MagicMock(), UsageType.LLM_COST, _TENANT)
            read.assert_not_called()

    def test_pending_amount_reaches_the_counter_check(self) -> None:
        session = MagicMock()
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
            patch.object(usage_limits, "is_tenant_on_trial_fn", return_value=False),
            patch.object(usage_limits, "get_limit_for_usage_type", return_value=10),
            patch.object(usage_limits, "check_usage_limit") as read,
        ):
            check_usage_and_raise(
                session, UsageType.API_CALLS, _TENANT, pending_amount=1
            )
            read.assert_called_once_with(
                db_session=session,
                usage_type=UsageType.API_CALLS,
                limit=10,
                pending_amount=1,
            )

    @pytest.mark.parametrize(
        ("usage_type", "is_trial", "current", "limit", "expected"),
        [
            (
                UsageType.LLM_COST,
                True,
                3250.0,
                3200.0,
                "LLM usage limit exceeded for trial account. Current cost: $32.50, "
                "Limit: $32.00 per week. Please use your own LLM API key, upgrade "
                "your plan, or wait for the next billing period (1 week).",
            ),
            (
                UsageType.CHUNKS_INDEXED,
                False,
                4_000_001.0,
                4_000_000.0,
                "Document indexing limit exceeded for paid account. Indexed: 4000001 "
                "chunks, Limit: 4000000 per week. Please upgrade your plan or wait "
                "for the next billing period.",
            ),
            (
                UsageType.API_CALLS,
                True,
                1.0,
                0.0,
                "API access is not available on trial accounts. Please upgrade to a "
                "paid plan to use the API and chat widget.",
            ),
            (
                UsageType.API_CALLS,
                False,
                40001.0,
                40000.0,
                "API call limit exceeded for paid account. Calls: 40001, Limit: 40000 "
                "per week. Please upgrade your plan or wait for the next billing period.",
            ),
            (
                UsageType.NON_STREAMING_API_CALLS,
                False,
                161.0,
                160.0,
                "Non-streaming API call limit exceeded for paid account. Calls: 161, "
                "Limit: 160 per week. Please upgrade your plan or wait for the next "
                "billing period.",
            ),
        ],
    )
    def test_over_the_limit_raises_429_with_the_known_wording(
        self,
        usage_type: UsageType,
        is_trial: bool,
        current: float,
        limit: float,
        expected: str,
    ) -> None:
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
            patch.object(usage_limits, "is_tenant_on_trial_fn", return_value=is_trial),
            patch.object(
                usage_limits, "get_limit_for_usage_type", return_value=int(limit)
            ),
            patch.object(
                usage_limits, "check_usage_limit", _over(usage_type, current, limit)
            ),
            pytest.raises(OnyxError) as exc_info,
        ):
            check_usage_and_raise(MagicMock(), usage_type, _TENANT)
        assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED
        assert exc_info.value.detail == expected


class TestCheckLlmCostLimitForProvider:
    def test_own_key_is_exempt(self) -> None:
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
            patch.object(usage_limits, "_ONYX_MANAGED_API_KEYS", {"onyx-key"}),
            patch.object(usage_limits, "check_usage_and_raise") as check,
        ):
            check_llm_cost_limit_for_provider(MagicMock(), _TENANT, "customer-key")
            check.assert_not_called()

    def test_managed_key_checks_current_usage(self) -> None:
        session = MagicMock()
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
            patch.object(usage_limits, "_ONYX_MANAGED_API_KEYS", {"onyx-key"}),
            patch.object(usage_limits, "check_usage_and_raise") as check,
        ):
            check_llm_cost_limit_for_provider(session, _TENANT, "onyx-key")
            check.assert_called_once_with(
                db_session=session,
                usage_type=UsageType.LLM_COST,
                tenant_id=_TENANT,
                pending_amount=0,
            )
