"""Admin CRUD for per-model cost overrides — negotiated rates that win over
litellm in compute_cost_cents. Writes invalidate the per-tenant override cache
so subsequent cost computations don't bill stale rates."""

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cost_overrides import delete_override
from onyx.llm.cost_overrides import invalidate_override_cache
from onyx.llm.cost_overrides import list_overrides
from onyx.llm.cost_overrides import upsert_override
from onyx.server.features.usage.models import CostOverride
from onyx.server.features.usage.models import CostOverrideUpsertRequest

router = APIRouter(prefix="/admin/cost-overrides", tags=PUBLIC_API_TAGS)


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
