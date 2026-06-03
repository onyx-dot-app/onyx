"""Admin CRUD for per-model cost overrides — negotiated rates that win over
litellm in compute_cost_cents. Writes invalidate the per-tenant override cache
so subsequent cost computations don't bill stale rates."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.users import current_user
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.llm import fetch_default_llm_model
from onyx.db.models import User
from onyx.db.user_usage import get_user_cost_cents_in_window
from onyx.db.user_usage import get_user_usage_by_day_and_model
from onyx.db.user_usage import get_window_start
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cost import get_model_price_per_million
from onyx.llm.cost_overrides import delete_override
from onyx.llm.cost_overrides import invalidate_override_cache
from onyx.llm.cost_overrides import list_overrides
from onyx.llm.cost_overrides import upsert_override
from onyx.server.features.usage.models import CostOverride
from onyx.server.features.usage.models import CostOverrideUpsertRequest
from onyx.server.features.usage.models import ModelPrice
from onyx.server.features.usage.models import UsageDayModel
from onyx.server.features.usage.models import UserUsageResponse
from shared_configs.configs import USAGE_LIMIT_WINDOW_SECONDS

# Per-user windows must coincide with the tenant-usage windows; same source as
# the recorder (onyx/tracing/processors/user_usage_processor.py).
_PERIOD_HOURS = USAGE_LIMIT_WINDOW_SECONDS // 3600

router = APIRouter(prefix="/admin/cost-overrides", tags=PUBLIC_API_TAGS)

user_usage_router = APIRouter(prefix="/user/usage", tags=PUBLIC_API_TAGS)


@user_usage_router.get("")
def get_my_usage(
    days: int | None = None,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserUsageResponse:
    """The calling user's own token/cost usage — backs the Usage tab.

    Aggregates the current window by default; `days` widens the per-day table to
    a trailing N-day range. Budget fields are null until P5 enforcement exists.
    """
    now = datetime.now(timezone.utc)
    window_start = get_window_start(now, period_hours=_PERIOD_HOURS)

    since = now - timedelta(days=days) if days else window_start
    user_id = str(user.id)

    per_day = [
        UsageDayModel.model_validate(row)
        for row in get_user_usage_by_day_and_model(
            db_session, user_id, since=since, until=now
        )
    ]
    window_cost_cents = get_user_cost_cents_in_window(db_session, user_id, window_start)

    # No per-user selected-model resolution exists yet; price the tenant default
    # chat model. Override-aware via the shared cost helper.
    default_model = fetch_default_llm_model(db_session)
    selected_model_price: ModelPrice | None = None
    if default_model is not None:
        provider = default_model.llm_provider.provider
        input_per_mtok, output_per_mtok = get_model_price_per_million(
            default_model.name, provider, db_session
        )
        selected_model_price = ModelPrice(
            model=default_model.name,
            provider=provider,
            input_per_mtok=input_per_mtok,
            output_per_mtok=output_per_mtok,
        )

    return UserUsageResponse(
        per_day_by_model=per_day,
        window_cost_cents=window_cost_cents,
        budget_cents=None,
        budget_remaining_cents=None,
        selected_model_price=selected_model_price,
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
        input_cost_per_mtok=payload.input_cost_per_mtok,
        output_cost_per_mtok=payload.output_cost_per_mtok,
    )
    db_session.commit()
    invalidate_override_cache()
    return CostOverride.from_db(row)


@router.delete("/{model}")
def delete_cost_override(
    model: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    if not delete_override(db_session, model):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"No cost override for model {model}")
    db_session.commit()
    invalidate_override_cache()
