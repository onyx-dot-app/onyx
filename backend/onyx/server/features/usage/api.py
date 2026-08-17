"""Admin cost overrides + user/usage endpoints."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.users import current_user
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.llm import (
    fetch_all_llm_providers_accessible_in_any_context,
    fetch_default_llm_model,
)
from onyx.db.models import TokenRateLimit, User
from onyx.db.token_limit import (
    fetch_all_global_token_rate_limits,
    fetch_all_user_token_rate_limits,
    fetch_user_group_token_rate_limits,
)
from onyx.db.user_usage import (
    get_cost_window_reset,
    get_cost_window_start,
    get_group_cost_cents_buckets_since,
    get_total_cost_cents_buckets_since,
    get_usage_export,
    get_usage_reset_window_start,
    get_user_cost_cents_buckets_since,
    get_user_cost_cents_since,
    get_user_usage_by_day_and_model,
    reset_user_usage,
)
from onyx.db.users import get_user_by_email
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cost import ModelPrice, get_model_price_per_million
from onyx.llm.cost_overrides import (
    delete_override,
    invalidate_override_cache,
    list_overrides,
    upsert_override,
)
from onyx.server.features.usage.models import (
    CostOverride,
    CostOverrideUpsertRequest,
    EffectiveCostBudget,
    ResetUsageRequest,
    ResetUsageResponse,
    UsageExportRecord,
    UsageExportResponse,
    UsageExportTotals,
    UsageExportUser,
    UserUsageResponse,
)
from onyx.utils.datetime import get_window_start
from shared_configs.configs import USAGE_LIMIT_WINDOW_SECONDS

# Default trailing range when no start is given.
_DEFAULT_USAGE_RANGE_INCLUSIVE_DAYS = 30


def _start_for_inclusive_range(end_date: date, inclusive_days: int) -> date:
    try:
        return end_date - timedelta(days=inclusive_days - 1)
    except OverflowError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "date range exceeds supported bounds"
        ) from error


def _date_range_to_utc_bounds(
    start_date: date, end_date: date
) -> tuple[datetime, datetime]:
    if start_date > end_date:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "start must not be after end")

    start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    try:
        end_dt = datetime.combine(
            end_date + timedelta(days=1), time.min, tzinfo=timezone.utc
        )
    except OverflowError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "date range exceeds supported bounds"
        ) from error
    return start_dt, end_dt


def _used_from_buckets(
    buckets: list[tuple[datetime, float]], cutoff: datetime
) -> float:
    return sum(c for ws, c in buckets if ws >= cutoff)


def _user_cost_budget(db_session: Session, user_id: str) -> EffectiveCostBudget | None:
    """Effective cost budget (most binding across user/global/group limits)."""
    now = datetime.now(tz=timezone.utc)
    candidates: list[EffectiveCostBudget] = []

    def _add_from_limits(
        limits: Sequence[TokenRateLimit],
        buckets: list[tuple[datetime, float]],
    ) -> None:
        for rl in limits:
            if rl.cost_budget_cents is None:
                continue
            cutoff = get_cost_window_start(now, rl.period_hours)
            used = _used_from_buckets(buckets, cutoff)
            candidates.append(
                EffectiveCostBudget(
                    budget_cents=rl.cost_budget_cents,
                    remaining_cents=rl.cost_budget_cents - used,
                    period_hours=rl.period_hours,
                    reset_at=get_cost_window_reset(now, rl.period_hours),
                )
            )

    user_rls = fetch_all_user_token_rate_limits(db_session, enabled_only=True)
    user_cost_rls = [rl for rl in user_rls if rl.cost_budget_cents is not None]
    if user_cost_rls:
        fetch_cutoff = min(
            get_cost_window_start(now, rl.period_hours) for rl in user_cost_rls
        )
        _add_from_limits(
            user_cost_rls,
            get_user_cost_cents_buckets_since(db_session, user_id, fetch_cutoff),
        )

    global_rls = fetch_all_global_token_rate_limits(db_session, enabled_only=True)
    global_cost_rls = [rl for rl in global_rls if rl.cost_budget_cents is not None]
    if global_cost_rls:
        fetch_cutoff = min(
            get_cost_window_start(now, rl.period_hours) for rl in global_cost_rls
        )
        _add_from_limits(
            global_cost_rls,
            get_total_cost_cents_buckets_since(db_session, fetch_cutoff),
        )

    group_candidate = _group_cost_budget_candidate(db_session, user_id, now)
    if group_candidate is not None:
        candidates.append(group_candidate)

    if not candidates:
        return None
    best = min(candidates, key=lambda c: c.remaining_cents)
    return EffectiveCostBudget(
        budget_cents=best.budget_cents,
        remaining_cents=max(best.remaining_cents, 0.0),
        period_hours=best.period_hours,
        reset_at=best.reset_at,
    )


def _group_cost_budget_candidate(
    db_session: Session, user_id: str, now: datetime
) -> EffectiveCostBudget | None:
    """Group cost headroom. Gate requires all groups over budget → pick most
    permissive; cost-exempt group exempts scope."""
    group_limits = fetch_user_group_token_rate_limits(db_session, UUID(user_id))
    if not group_limits:
        return None

    cost_rls = [
        rl
        for rls in group_limits.values()
        for rl in rls
        if rl.cost_budget_cents is not None
    ]
    if not cost_rls:
        return None

    # One batched query for every group's cost buckets, then window in Python.
    fetch_cutoff = min(get_cost_window_start(now, rl.period_hours) for rl in cost_rls)
    buckets = get_group_cost_cents_buckets_since(
        db_session, list(group_limits.keys()), fetch_cutoff
    )

    most_permissive: EffectiveCostBudget | None = None
    for group_id, limits in group_limits.items():
        group_buckets = buckets.get(group_id, [])
        group_binding: EffectiveCostBudget | None = None
        for rl in limits:
            if rl.cost_budget_cents is None:
                continue
            cutoff = get_cost_window_start(now, rl.period_hours)
            used = _used_from_buckets(group_buckets, cutoff)
            remaining = rl.cost_budget_cents - used
            if group_binding is None or remaining < group_binding.remaining_cents:
                group_binding = EffectiveCostBudget(
                    budget_cents=rl.cost_budget_cents,
                    remaining_cents=remaining,
                    period_hours=rl.period_hours,
                    reset_at=get_cost_window_reset(now, rl.period_hours),
                )
        if group_binding is None:
            return None  # a cost-exempt group exempts the whole group scope
        if (
            most_permissive is None
            or group_binding.remaining_cents > most_permissive.remaining_cents
        ):
            most_permissive = group_binding

    return most_permissive


router = APIRouter(prefix="/admin/cost-overrides", tags=PUBLIC_API_TAGS)

user_usage_router = APIRouter(prefix="/user/usage", tags=PUBLIC_API_TAGS)

admin_usage_router = APIRouter(prefix="/admin/usage", tags=PUBLIC_API_TAGS)


@user_usage_router.get("")
def get_my_usage(
    days: Annotated[int | None, Query(ge=1, le=3_650)] = None,
    start: date | None = None,
    end: date | None = None,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserUsageResponse:
    """Caller's token/cost usage for the Usage tab."""
    now = datetime.now(timezone.utc)
    window_start = get_window_start(now, period_seconds=USAGE_LIMIT_WINDOW_SECONDS)

    if start is not None or end is not None:
        end_date = end or now.date()
        inclusive_days = days or _DEFAULT_USAGE_RANGE_INCLUSIVE_DAYS
        start_date = start or _start_for_inclusive_range(end_date, inclusive_days)
        since, until = _date_range_to_utc_bounds(start_date, end_date)
    elif days is not None:
        since = now - timedelta(days=days)
        until = now
    else:
        since = window_start
        until = now
    user_id = str(user.id)

    per_day = get_user_usage_by_day_and_model(
        db_session, user_id, since=since, until=until
    )
    window_cost_cents = (
        sum(row.cost_cents for row in per_day)
        if start is not None or end is not None
        else get_user_cost_cents_since(db_session, user_id, window_start)
    )

    accessible_providers = fetch_all_llm_providers_accessible_in_any_context(
        db_session, user
    )
    available_model_prices: list[ModelPrice] = []
    accessible_model_configuration_ids: set[int] = set()
    seen: set[tuple[str, str]] = set()
    for provider in accessible_providers:
        for model_configuration in provider.model_configurations:
            if not model_configuration.is_visible:
                continue
            if model_configuration.id is not None:
                accessible_model_configuration_ids.add(model_configuration.id)
            key = (provider.provider, model_configuration.name)
            if key in seen:
                continue
            seen.add(key)
            price = get_model_price_per_million(
                model_configuration.name, provider.provider, db_session
            )
            if price.input_per_mtok is not None and price.output_per_mtok is not None:
                available_model_prices.append(price)
    available_model_prices.sort(key=lambda p: (p.input_per_mtok or 0.0, p.model))

    default_model = fetch_default_llm_model(db_session)
    selected_model_price: ModelPrice | None = None
    if (
        default_model is not None
        and default_model.id in accessible_model_configuration_ids
    ):
        provider = default_model.llm_provider.provider
        price = get_model_price_per_million(default_model.name, provider, db_session)
        if price.input_per_mtok is not None and price.output_per_mtok is not None:
            selected_model_price = price

    budget = _user_cost_budget(db_session, user_id)

    return UserUsageResponse(
        per_day_by_model=per_day,
        window_cost_cents=window_cost_cents,
        budget_cents=budget.budget_cents if budget is not None else None,
        budget_remaining_cents=(budget.remaining_cents if budget is not None else None),
        budget_period_hours=budget.period_hours if budget is not None else None,
        budget_reset_at=budget.reset_at if budget is not None else None,
        selected_model_price=selected_model_price,
        available_model_prices=available_model_prices,
    )


@admin_usage_router.get("/export")
def export_usage(
    start: date | None = None,
    end: date | None = None,
    model: str | None = None,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> UsageExportResponse:
    """Company-wide daily usage export by email."""
    end_date = end or datetime.now(timezone.utc).date()
    start_date = start or _start_for_inclusive_range(
        end_date, _DEFAULT_USAGE_RANGE_INCLUSIVE_DAYS
    )
    start_dt, end_dt = _date_range_to_utc_bounds(start_date, end_date)

    # TODO(evan-onyx): this might need to be done in a background task
    rows = get_usage_export(db_session, start=start_dt, end=end_dt, model=model)

    records_by_email: dict[str, list[UsageExportRecord]] = defaultdict(list)
    for row in rows:
        records_by_email[row.email].append(
            UsageExportRecord.model_validate(row.model_dump(exclude={"email"}))
        )

    users = [
        UsageExportUser(
            email=email,
            totals=UsageExportTotals(
                input_tokens=sum(r.input_tokens for r in records),
                output_tokens=sum(r.output_tokens for r in records),
                cache_read_tokens=sum(r.cache_read_tokens for r in records),
                cache_creation_tokens=sum(r.cache_creation_tokens for r in records),
                cost_cents=sum(r.cost_cents for r in records),
            ),
            records=records,
        )
        for email, records in records_by_email.items()
    ]

    return UsageExportResponse(
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        users=users,
    )


@admin_usage_router.post("/reset")
def reset_usage(
    payload: ResetUsageRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ResetUsageResponse:
    """Clear a user's usage across every applicable active limit window."""
    user = get_user_by_email(payload.user_email, db_session)
    if user is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User not found")

    user_id = str(user.id)
    group_limits = fetch_user_group_token_rate_limits(db_session, user.id)
    rate_limits = [
        *fetch_all_user_token_rate_limits(db_session, enabled_only=True),
        *fetch_all_global_token_rate_limits(db_session, enabled_only=True),
        *(limit for limits in group_limits.values() for limit in limits),
    ]
    window_start = get_usage_reset_window_start(datetime.now(timezone.utc), rate_limits)
    reset_rows = reset_user_usage(db_session, user_id, window_start)
    db_session.commit()
    return ResetUsageResponse(reset_rows=reset_rows)


@router.get("")
def list_cost_overrides(
    _: User = Depends(require_permission(Permission.MANAGE_LLMS)),
    db_session: Session = Depends(get_session),
) -> list[CostOverride]:
    return [CostOverride.from_db(row) for row in list_overrides(db_session)]


@router.put("")
def upsert_cost_override(
    payload: CostOverrideUpsertRequest,
    _: User = Depends(require_permission(Permission.MANAGE_LLMS)),
    db_session: Session = Depends(get_session),
) -> CostOverride:
    row = upsert_override(
        db_session,
        model=payload.model,
        provider=payload.provider,
        input_cost_per_mtok=payload.input_cost_per_mtok,
        output_cost_per_mtok=payload.output_cost_per_mtok,
        cache_read_cost_per_mtok=payload.cache_read_cost_per_mtok,
    )
    db_session.commit()
    invalidate_override_cache()
    return CostOverride.from_db(row)


# {model:path} so slash-containing model ids (e.g. "bedrock/anthropic.claude")
# match instead of 404-ing on the first path segment.
@router.delete("/{model:path}")
def delete_cost_override(
    model: str,
    provider: str = "",
    _: User = Depends(require_permission(Permission.MANAGE_LLMS)),
    db_session: Session = Depends(get_session),
) -> None:
    if not delete_override(db_session, model, provider):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"No cost override for model {model}")
    db_session.commit()
    invalidate_override_cache()
