"""Unit tests for the usage limit policies, their windows and enforcement."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, MagicMock, patch

import pytest

from onyx.db.usage import UsageLimitExceededError, UsagePeriod, UsageType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server import usage_limits
from onyx.server.models import (
    Allowance,
    LimitMeasure,
    LimitPolicy,
    LimitPolicyName,
    LimitScope,
    LimitWindow,
    WindowAnchor,
)
from onyx.server.tenant_usage_limits import TenantUsageLimitOverrides
from onyx.server.usage_limits import (
    CALENDAR_WEEK,
    CLOUD_PAID,
    CLOUD_TRIAL,
    NO_LIMIT,
    PLAYGROUND,
    TENANT_WEEK,
    WHOLE_TRIAL,
    check_llm_cost_limit_for_provider,
    check_usage_and_raise,
    get_limit_for_usage_type,
    period_for,
    policy_for_plan,
    record_usage,
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
        assert {CLOUD_TRIAL.name, CLOUD_PAID.name, PLAYGROUND.name} == set(
            LimitPolicyName
        )

    def test_plan_selects_policy(self) -> None:
        assert policy_for_plan(True) is CLOUD_TRIAL
        assert policy_for_plan(False) is CLOUD_PAID

    def test_calendar_window_without_length_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="needs a length"):
            LimitWindow(anchor=WindowAnchor.CALENDAR)

    def test_non_positive_window_length_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            LimitWindow(anchor=WindowAnchor.TENANT_START, length_seconds=0)

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
                period=ANY,
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


_START = datetime(2026, 11, 25, 14, 7, tzinfo=timezone.utc)  # a Wednesday afternoon


@pytest.fixture(autouse=True)
def _empty_trial_start_warnings() -> Generator[None, None, None]:
    """Every test starts with no recorded warnings and leaves none behind:
    period_for records one whenever the trial start is missing."""
    with patch.dict(usage_limits._trial_start_warned_at, {}, clear=True):
        yield


class TestPeriodFor:
    def test_calendar_week_runs_monday_to_monday(self) -> None:
        now = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
        week = LimitWindow(anchor=WindowAnchor.CALENDAR, length_seconds=604_800)
        monday = datetime(2026, 11, 23, tzinfo=timezone.utc)
        assert period_for(week, "t", now) == UsagePeriod(
            anchor=WindowAnchor.CALENDAR, start=monday, end=monday + timedelta(days=7)
        )

    def test_calendar_day_is_honoured(self) -> None:
        day = LimitWindow(anchor=WindowAnchor.CALENDAR, length_seconds=86_400)
        now = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
        midnight = datetime(2026, 11, 27, tzinfo=timezone.utc)
        assert period_for(day, "t", now) == UsagePeriod(
            anchor=WindowAnchor.CALENDAR,
            start=midnight,
            end=midnight + timedelta(days=1),
        )

    @pytest.mark.parametrize(
        ("elapsed", "window_number"),
        [
            (timedelta(0), 0),
            (timedelta(days=6, hours=23, minutes=59), 0),
            (timedelta(days=7), 1),
            (timedelta(days=13, hours=23), 1),
            (timedelta(days=14), 2),
        ],
    )
    def test_tenant_week_counts_seven_days_from_the_trial_start(
        self, elapsed: timedelta, window_number: int
    ) -> None:
        block_start = _START + timedelta(days=7 * window_number)
        with patch.object(usage_limits, "tenant_trial_start_fn", return_value=_START):
            assert period_for(TENANT_WEEK, "t", _START + elapsed) == UsagePeriod(
                anchor=WindowAnchor.TENANT_START,
                start=block_start,
                end=block_start + timedelta(days=7),
            )

    def test_whole_trial_is_one_period_that_never_ends(self) -> None:
        with patch.object(usage_limits, "tenant_trial_start_fn", return_value=_START):
            assert period_for(
                WHOLE_TRIAL, "t", _START + timedelta(days=20)
            ) == UsagePeriod(anchor=WindowAnchor.TENANT_START, start=_START)

    @pytest.mark.parametrize(
        "start",
        [None, _START.replace(tzinfo=None), _START + timedelta(days=1)],
        ids=["missing", "naive", "in_the_future"],
    )
    def test_invalid_trial_start_falls_back_to_the_calendar_week(
        self, start: datetime | None
    ) -> None:
        monday = datetime(2026, 11, 23, tzinfo=timezone.utc)
        with (
            patch.object(usage_limits, "tenant_trial_start_fn", return_value=start),
            patch("onyx.db.usage.USAGE_LIMIT_WINDOW_SECONDS", 604_800),
        ):
            assert period_for(TENANT_WEEK, "t", _START) == UsagePeriod(
                anchor=WindowAnchor.CALENDAR,
                start=monday,
                end=monday + timedelta(days=7),
            )


class TestLengthWithoutATrialStart:
    def test_falls_back_to_calendar_periods_of_its_own_length(self) -> None:
        """A one-day limit counted from the trial start falls back to calendar
        days, not calendar weeks."""
        one_day = LimitWindow(anchor=WindowAnchor.TENANT_START, length_seconds=86_400)
        midnight = datetime(2026, 11, 25, tzinfo=timezone.utc)
        with patch.object(usage_limits, "tenant_trial_start_fn", return_value=None):
            assert period_for(one_day, "t", _START) == UsagePeriod(
                anchor=WindowAnchor.CALENDAR,
                start=midnight,
                end=midnight + timedelta(days=1),
            )


class TestWholeTrialWithoutATrialStart:
    @pytest.mark.parametrize(
        "start",
        [None, _START.replace(tzinfo=None), _START + timedelta(days=30)],
        ids=["missing", "naive", "in_the_future"],
    )
    def test_counts_in_one_period_that_never_ends(self, start: datetime | None) -> None:
        """A whole-trial limit must not reset weekly when the trial start is
        missing: every week lands in the same period."""
        with patch.object(usage_limits, "tenant_trial_start_fn", return_value=start):
            this_week = period_for(WHOLE_TRIAL, "t", _START)
            weeks_later = period_for(WHOLE_TRIAL, "t", _START + timedelta(days=20))
        assert this_week == weeks_later
        assert this_week.end is None


class TestPlayground:
    def test_policy_splits_cost_weekly_and_counts_chunks_for_the_whole_trial(
        self,
    ) -> None:
        assert PLAYGROUND.allowances[UsageType.LLM_COST].window == TENANT_WEEK
        assert PLAYGROUND.allowances[UsageType.CHUNKS_INDEXED].window == WHOLE_TRIAL
        assert UsageType.API_CALLS not in PLAYGROUND.allowances
        assert UsageType.NON_STREAMING_API_CALLS not in PLAYGROUND.allowances

    def test_every_tenant_is_held_to_the_playground_policy(self) -> None:
        with patch.object(usage_limits, "IS_PLAYGROUND", True):
            assert policy_for_plan(True) is PLAYGROUND
            assert policy_for_plan(False) is PLAYGROUND

    def test_check_skips_the_billing_lookup(self) -> None:
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
            patch.object(usage_limits, "IS_PLAYGROUND", True),
            patch.object(usage_limits, "is_tenant_on_trial_fn") as billing,
            patch.object(usage_limits, "check_usage_limit"),
        ):
            check_usage_and_raise(MagicMock(), UsageType.LLM_COST, _TENANT)
            billing.assert_not_called()

    def test_api_calls_are_not_limited(self) -> None:
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
            patch.object(usage_limits, "IS_PLAYGROUND", True),
            patch.object(usage_limits, "check_usage_limit") as read,
        ):
            check_usage_and_raise(
                MagicMock(), UsageType.API_CALLS, _TENANT, pending_amount=1
            )
            read.assert_not_called()

    def test_cost_is_read_from_the_current_tenant_week_row(self) -> None:
        session = MagicMock()
        with (
            patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
            patch.object(usage_limits, "IS_PLAYGROUND", True),
            patch.object(usage_limits, "tenant_trial_start_fn", return_value=_START),
            patch.object(usage_limits, "check_usage_limit") as read,
        ):
            check_usage_and_raise(session, UsageType.LLM_COST, _TENANT)
        period = read.call_args.kwargs["period"]
        assert period.anchor == WindowAnchor.TENANT_START
        assert period.start >= _START
        assert (period.start - _START) % timedelta(days=7) == timedelta(0)
        assert period.end == period.start + timedelta(days=7)
        assert (
            read.call_args.kwargs["limit"]
            == PLAYGROUND.allowances[UsageType.LLM_COST].limit
        )


class TestRecordUsage:
    def test_cloud_adds_to_the_calendar_week_row(self) -> None:
        session = MagicMock()
        with (
            patch.object(usage_limits, "_INCREMENT_POLICY", CLOUD_TRIAL),
            patch.object(usage_limits.tenant_usage_db, "increment_usage") as add,
            patch.object(usage_limits, "is_tenant_on_trial_fn") as billing,
        ):
            record_usage(session, UsageType.LLM_COST, 12.5, _TENANT)
        billing.assert_not_called()
        add.assert_called_once_with(
            session,
            UsageType.LLM_COST,
            12.5,
            period_for(CALENDAR_WEEK, _TENANT),
        )

    def test_playground_adds_to_the_same_row_the_check_reads(self) -> None:
        now = _START + timedelta(days=9)
        with (
            patch.object(usage_limits, "_INCREMENT_POLICY", PLAYGROUND),
            patch.object(usage_limits, "tenant_trial_start_fn", return_value=_START),
            patch.object(usage_limits.tenant_usage_db, "increment_usage") as add,
            patch.object(usage_limits, "datetime") as clock,
        ):
            clock.now.return_value = now
            record_usage(MagicMock(), UsageType.LLM_COST, 1, _TENANT)
        assert add.call_args.args[3] == UsagePeriod(
            anchor=WindowAnchor.TENANT_START,
            start=_START + timedelta(days=7),
            end=_START + timedelta(days=14),
        )

    def test_type_the_policy_does_not_list_uses_the_default_row(self) -> None:
        with (
            patch.object(usage_limits, "_INCREMENT_POLICY", PLAYGROUND),
            patch.object(usage_limits.tenant_usage_db, "increment_usage") as add,
        ):
            record_usage(MagicMock(), UsageType.API_CALLS, 1, _TENANT)
        assert add.call_args.args[3] is None


class TestPlaygroundOverrides:
    def test_override_from_the_control_plane_replaces_the_amount(self) -> None:
        with (
            patch.object(usage_limits, "IS_PLAYGROUND", True),
            patch.object(usage_limits, "tenant_limit_override_fn", return_value=15000),
            patch.object(usage_limits, "_get_tenant_override") as legacy,
        ):
            assert get_limit_for_usage_type(UsageType.LLM_COST, True, _TENANT) == 15000
        legacy.assert_not_called()

    def test_no_override_means_the_playground_amount(self) -> None:
        with (
            patch.object(usage_limits, "IS_PLAYGROUND", True),
            patch.object(usage_limits, "tenant_limit_override_fn", return_value=None),
        ):
            assert (
                get_limit_for_usage_type(UsageType.CHUNKS_INDEXED, True, _TENANT)
                == PLAYGROUND.allowances[UsageType.CHUNKS_INDEXED].limit
            )

    def test_cloud_never_reads_the_playground_source(self) -> None:
        with (
            patch.object(usage_limits, "IS_PLAYGROUND", False),
            patch.object(usage_limits, "tenant_limit_override_fn") as playground,
            patch.object(usage_limits, "_get_tenant_override", return_value=None),
        ):
            get_limit_for_usage_type(UsageType.LLM_COST, True, _TENANT)
        playground.assert_not_called()


class TestMissingTrialStartWarning:
    def test_warns_once_an_hour_per_tenant(self) -> None:
        with (
            patch.object(usage_limits, "tenant_trial_start_fn", return_value=None),
            patch.object(usage_limits, "logger") as log,
            patch.object(usage_limits.time, "monotonic", side_effect=[0, 10, 10, 4000]),
        ):
            period_for(TENANT_WEEK, "t1", _START)
            period_for(TENANT_WEEK, "t1", _START)
            period_for(TENANT_WEEK, "t2", _START)
            period_for(TENANT_WEEK, "t1", _START)
        warned = [c.args[1] for c in log.warning.call_args_list]
        assert warned == ["t1", "t2", "t1"]
