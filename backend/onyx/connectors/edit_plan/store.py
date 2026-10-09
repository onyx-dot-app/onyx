"""Computed edit plans, kept in the tenant's cache backend for a day so the
admin can review a plan and apply it later.

A plan is tied to the base state it was computed from. Apply checks that the
pair still has that base state, so a plan never runs against a pair that
changed after it was computed.
"""

import hashlib
import json
from uuid import UUID

from onyx.cache.factory import get_cache_backend
from onyx.connectors.edit_plan.constants import EDIT_PLAN_TTL_SECONDS
from onyx.connectors.edit_plan.models import PairState, StoredEditPlan
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_EDIT_PLAN_KEY_PREFIX = "connector_edit_plan"


def compute_base_state_hash(state: PairState) -> str:
    """The sha256 of the state fields that decide a plan's steps. Pair
    settings (name, frequencies) are left out: a plan only overwrites them."""
    canonical = json.dumps(
        state.model_dump(
            mode="json",
            include={
                "source",
                "input_type",
                "connector_specific_config",
                "access_type",
                "data_access_group_ids",
                "credential_id",
                "indexing_start",
            },
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _plan_key(plan_id: UUID) -> str:
    return f"{_EDIT_PLAN_KEY_PREFIX}:{plan_id}"


def save_edit_plan(stored: StoredEditPlan) -> None:
    get_cache_backend().set(
        _plan_key(stored.plan_id),
        stored.model_dump_json(),
        ex=EDIT_PLAN_TTL_SECONDS,
    )


def load_edit_plan(plan_id: UUID, cc_pair_id: int) -> StoredEditPlan | None:
    """The current tenant's plan for this pair, or None when it expired or
    belongs to another pair."""
    raw = get_cache_backend().get(_plan_key(plan_id))
    if raw is None:
        return None
    stored = StoredEditPlan.model_validate_json(raw)
    return stored if stored.cc_pair_id == cc_pair_id else None


def ensure_base_state_matches(stored: StoredEditPlan, current: PairState) -> None:
    """Raises ``OnyxError`` (EDIT_PLAN_STALE) when the pair changed since the
    plan was computed."""
    if compute_base_state_hash(current) != stored.base_state_hash:
        raise OnyxError(
            OnyxErrorCode.EDIT_PLAN_STALE,
            "The connector changed after this plan was computed. Compute a new plan.",
        )
