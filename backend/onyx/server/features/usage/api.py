"""Admin cost overrides + user/usage endpoints."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.users import current_user
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.llm import fetch_default_llm_model
from onyx.db.models import TokenRateLimit
from onyx.db.models import User
from onyx.db.token_limit import fetch_all_global_token_rate_limits
from onyx.db.token_limit import fetch_all_user_token_rate_limits
from onyx.db.token_limit import fetch_user_group_token_rate_limits
from onyx.db.usage import USAGE_PERIOD_SECONDS
from onyx.db.user_usage import get_group_cost_cents_buckets_since
from onyx.db.user_usage import get_total_cost_cents_buckets_since
from onyx.db.user_usage import get_usage_export
from onyx.db.user_usage import get_user_cost_cents_buckets_since
from onyx.db.user_usage import get_user_cost_cents_in_window
from onyx.db.user_usage import get_user_usage_by_day_and_model
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cost import get_model_price_per_million
from onyx.llm.cost_overrides import delete_override
from onyx.llm.cost_overrides import invalidate_override_cache
from onyx.llm.cost_overrides import list_overrides
from onyx.llm.cost_overrides import upsert_override
from onyx.server.features.usage.models import CostOverride
from onyx.server.features.usage.models import CostOverrideUpsertRequest
from onyx.server.features.usage.models import EffectiveCostBudget
from onyx.server.features.usage.models import ModelPrice
from onyx.server.features.usage.models import UsageExportRecord
from onyx.server.features.usage.models import UsageExportResponse
from onyx.server.features.usage.models import UsageExportTotals
from onyx.server.features.usage.models import UsageExportUser
from onyx.server.features.usage.models import UserUsageResponse
from onyx.utils.datetime import get_window_start
from shared_configs.configs import USAGE_LIMIT_WINDOW_SECONDS

# Default trailing range for the export when no start is given.
_DEFAULT_EXPORT_DAYS = 30

# Ledger grid; relax cutoff like cost gate so UI matches enforcement.
_LEDGER_GRID = timedelta(seconds=USAGE_LIMIT_WINDOW_SECONDS)


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
            cutoff = now - timedelta(hours=rl.period_hours) - _LEDGER_GRID
            used = _used_from_buckets(buckets, cutoff)
            candidates.append(
                EffectiveCostBudget(
                    budget_cents=rl.cost_budget_cents,
                    remaining_cents=rl.cost_budget_cents - used,
                    period_hours=rl.period_hours,
                )
            )

    user_rls = fetch_all_user_token_rate_limits(db_session, enabled_only=True)
    user_cost_rls = [rl for rl in user_rls if rl.cost_budget_cents is not None]
    if user_cost_rls:
        broadest = max(rl.period_hours for rl in user_cost_rls)
        fetch_cutoff = now - timedelta(hours=broadest) - _LEDGER_GRID
        _add_from_limits(
            user_cost_rls,
            get_user_cost_cents_buckets_since(db_session, user_id, fetch_cutoff),
        )

    global_rls = fetch_all_global_token_rate_limits(db_session, enabled_only=True)
    global_cost_rls = [rl for rl in global_rls if rl.cost_budget_cents is not None]
    if global_cost_rls:
        broadest = max(rl.period_hours for rl in global_cost_rls)
        fetch_cutoff = now - timedelta(hours=broadest) - _LEDGER_GRID
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
    broadest = max(rl.period_hours for rl in cost_rls)
    fetch_cutoff = now - timedelta(hours=broadest) - _LEDGER_GRID
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
            cutoff = now - timedelta(hours=rl.period_hours) - _LEDGER_GRID
            used = _used_from_buckets(group_buckets, cutoff)
            remaining = rl.cost_budget_cents - used
            if group_binding is None or remaining < group_binding.remaining_cents:
                group_binding = EffectiveCostBudget(
                    budget_cents=rl.cost_budget_cents,
                    remaining_cents=remaining,
                    period_hours=rl.period_hours,
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
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserUsageResponse:
    """Caller's token/cost usage for the Usage tab."""
    now = datetime.now(timezone.utc)
    window_start = get_window_start(now, period_seconds=USAGE_PERIOD_SECONDS)

    since = now - timedelta(days=days) if days else window_start
    user_id = str(user.id)

    per_day = get_user_usage_by_day_and_model(
        db_session, user_id, since=since, until=now
    )
    window_cost_cents = get_user_cost_cents_in_window(db_session, user_id, window_start)

    # Price tenant default chat model (no per-user model selection yet).
    default_model = fetch_default_llm_model(db_session)
    selected_model_price: ModelPrice | None = None
    if default_model is not None:
        provider = default_model.llm_provider.provider
        input_per_mtok, output_per_mtok = get_model_price_per_million(
            default_model.name, provider, db_session
        )
        # Omit price block unless both input/output rates known.
        if input_per_mtok is not None and output_per_mtok is not None:
            selected_model_price = ModelPrice(
                model=default_model.name,
                provider=provider,
                input_per_mtok=input_per_mtok,
                output_per_mtok=output_per_mtok,
            )

    budget = _user_cost_budget(db_session, user_id)

    return UserUsageResponse(
        per_day_by_model=per_day,
        window_cost_cents=window_cost_cents,
        budget_cents=budget.budget_cents if budget is not None else None,
        budget_remaining_cents=(budget.remaining_cents if budget is not None else None),
        budget_period_hours=budget.period_hours if budget is not None else None,
        selected_model_price=selected_model_price,
    )


@admin_usage_router.get("/export")
def export_usage(
    start: date | None = None,
    end: date | None = None,
    model: str | None = None,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> UsageExportResponse:
    """Company-wide usage export by email; day = window start, not call calendar day."""
    end_date = end or datetime.now(timezone.utc).date()
    start_date = start or (end_date - timedelta(days=_DEFAULT_EXPORT_DAYS))
    if start_date > end_date:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "start must not be after end")

    # Half-open over the full end day so windows starting on `end` are included.
    start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, time.min, tzinfo=timezone.utc) + timedelta(
        days=1
    )

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


@router.get("")
def list_cost_overrides(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[CostOverride]:
    return [CostOverride.from_db(row) for row in list_overrides(db_session)]


@router.put("")
def upsert_cost_override(
    payload: CostOverrideUpsertRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
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
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    if not delete_override(db_session, model, provider):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"No cost override for model {model}")
    db_session.commit()
    invalidate_override_cache()
