"""EE spending limit strategy. Three checks run in parallel, and each must pass:

- workspace pool (GLOBAL): every budget must have room.
- group pools (USER_GROUP): the user passes if any of their groups with an
  applicable pool has room; pools never block across groups.
- per-user allowance: for each (period, unit), the largest USER_GROUP_MEMBER
  budget among the user's groups, else the workspace default (USER). Only the
  user's own usage counts against it.

A check on one model reads only that model's limits and usage."""

from datetime import datetime, timezone
from uuid import UUID

from onyx.configs.constants import TokenRateLimitPeriod, TokenRateLimitScope
from onyx.db.api_key import is_api_key_email_address
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType
from onyx.db.models import TokenRateLimit, User
from onyx.db.token_limit import (
    fetch_enforced_token_rate_limits,
    fetch_user_group_enforced_token_rate_limits,
)
from onyx.db.user_usage import (
    get_group_cost_cents_buckets_since,
    get_group_token_buckets_since,
    get_user_cost_cents_buckets_since,
    get_user_token_buckets_since,
)
from onyx.server.query_and_chat.token_limit import (
    BudgetUnit,
    BudgetWindow,
    WindowUsage,
    _user_is_rate_limited_by_global,
    budget_windows,
    exhausted_windows,
    latest_reset,
    raise_rate_limited,
    token_buckets,
    usage_cutoff,
)
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def _check_spend_limits(user: User, model_configuration_id: int | None) -> None:
    # Shared principals carry traffic for many callers, so only the workspace
    # pool applies to them.
    if (
        user.is_anonymous
        or user.account_type == AccountType.SERVICE_ACCOUNT
        or is_api_key_email_address(user.email)
    ):
        _user_is_rate_limited_by_global(model_configuration_id)
        return

    run_functions_tuples_in_parallel(
        [
            (_user_is_rate_limited, (user.id, model_configuration_id)),
            (_user_is_rate_limited_by_group, (user.id, model_configuration_id)),
            (_user_is_rate_limited_by_global, (model_configuration_id,)),
        ]
    )


"""
Per-user allowance
"""


def resolve_member_allowance(
    default_limits: list[TokenRateLimit],
    member_limits_by_group: dict[int, list[TokenRateLimit]],
) -> list[BudgetWindow]:
    """The user's budget for each (period, unit): the largest among their
    groups that set it, else the workspace default. A group that doesn't set a
    bucket has no say in it."""
    allowance: dict[tuple[TokenRateLimitPeriod, BudgetUnit], BudgetWindow] = {}
    for group_id, limits in member_limits_by_group.items():
        for window in budget_windows(limits, user_group_id=group_id):
            key = (window.period, window.unit)
            current = allowance.get(key)
            if current is None or window.budget > current.budget:
                allowance[key] = window
    for window in budget_windows(default_limits):
        allowance.setdefault((window.period, window.unit), window)
    return list(allowance.values())


def _user_is_rate_limited(user_id: UUID, model_configuration_id: int | None) -> None:
    with get_session_with_current_tenant() as db_session:
        windows = resolve_member_allowance(
            list(
                fetch_enforced_token_rate_limits(
                    db_session, TokenRateLimitScope.USER, model_configuration_id
                )
            ),
            fetch_user_group_enforced_token_rate_limits(
                db_session,
                user_id,
                TokenRateLimitScope.USER_GROUP_MEMBER,
                model_configuration_id,
            ),
        )
        if not windows:
            return

        now = datetime.now(timezone.utc)
        usage = WindowUsage()
        if token_cutoff := usage_cutoff(now, windows, BudgetUnit.TOKENS):
            usage.tokens = token_buckets(
                get_user_token_buckets_since(
                    db_session, str(user_id), token_cutoff, model_configuration_id
                )
            )
        if cost_cutoff := usage_cutoff(now, windows, BudgetUnit.COST):
            usage.cost_cents = get_user_cost_cents_buckets_since(
                db_session, str(user_id), cost_cutoff, model_configuration_id
            )

    exhausted = exhausted_windows(windows, usage)
    if reset := latest_reset(exhausted):
        from_group = any(window.user_group_id is not None for window, _ in exhausted)
        raise_rate_limited(
            (
                TokenRateLimitScope.USER_GROUP_MEMBER
                if from_group
                else TokenRateLimitScope.USER
            ),
            reset,
            model_configuration_id,
        )


"""
Group pools
"""


def _user_is_rate_limited_by_group(
    user_id: UUID, model_configuration_id: int | None
) -> None:
    with get_session_with_current_tenant() as db_session:
        windows_by_group = {
            group_id: windows
            for group_id, limits in fetch_user_group_enforced_token_rate_limits(
                db_session,
                user_id,
                TokenRateLimitScope.USER_GROUP,
                model_configuration_id,
            ).items()
            if (windows := budget_windows(limits))
        }
        if not windows_by_group:
            return

        all_windows = [w for windows in windows_by_group.values() for w in windows]
        group_ids = list(windows_by_group)
        now = datetime.now(timezone.utc)
        usage_by_group = {group_id: WindowUsage() for group_id in group_ids}
        if token_cutoff := usage_cutoff(now, all_windows, BudgetUnit.TOKENS):
            for group_id, buckets in get_group_token_buckets_since(
                db_session, group_ids, token_cutoff, model_configuration_id
            ).items():
                usage_by_group[group_id].tokens = token_buckets(buckets)
        if cost_cutoff := usage_cutoff(now, all_windows, BudgetUnit.COST):
            for group_id, cost_buckets in get_group_cost_cents_buckets_since(
                db_session, group_ids, cost_cutoff, model_configuration_id
            ).items():
                usage_by_group[group_id].cost_cents = cost_buckets

    group_resets: list[datetime] = []
    for group_id, windows in windows_by_group.items():
        reset = latest_reset(exhausted_windows(windows, usage_by_group[group_id]))
        # A group with room unblocks the user entirely.
        if reset is None:
            return
        group_resets.append(reset)

    raise_rate_limited(
        TokenRateLimitScope.USER_GROUP, min(group_resets), model_configuration_id
    )
