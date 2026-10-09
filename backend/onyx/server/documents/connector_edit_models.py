"""Request and response models of the connector edit endpoints."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from onyx.connectors.capability_checks.draft_runs import DraftRerunMode
from onyx.connectors.edit_plan.constants import EDIT_PLAN_TTL_SECONDS
from onyx.connectors.edit_plan.models import (
    EditPlan,
    EditPlanChoices,
    EditStep,
    ProposedPairState,
    StoredEditPlan,
)
from onyx.db.enums import AccessType


class ConnectorEditProposal(BaseModel):
    """The full proposed state of the pair. Source and input type cannot
    change, so they are not part of it."""

    model_config = ConfigDict(extra="forbid")

    connector_specific_config: dict[str, Any]
    access_type: AccessType
    data_access_group_ids: list[int] = []
    credential_id: int
    indexing_start: datetime | None = None
    name: str
    refresh_freq: int | None = None
    prune_freq: int | None = None


class ConnectorEditPlanResponse(BaseModel):
    plan_id: UUID
    cc_pair_id: int
    created_at: datetime
    expires_at: datetime
    proposed: ProposedPairState
    # Steps, notes, the choices to make, validation, dry-run results and the
    # indexed document count.
    plan: EditPlan
    validation_blocks_apply: bool
    # POST here to run the slow checks on the proposed state, then GET the
    # plan again for their results.
    dry_run_checks_path: str

    @classmethod
    def from_stored(cls, stored: StoredEditPlan) -> "ConnectorEditPlanResponse":
        return cls(
            plan_id=stored.plan_id,
            cc_pair_id=stored.cc_pair_id,
            created_at=stored.created_at,
            expires_at=stored.created_at + timedelta(seconds=EDIT_PLAN_TTL_SECONDS),
            proposed=stored.proposed,
            plan=stored.plan,
            validation_blocks_apply=stored.plan.validation_blocks_apply,
            dry_run_checks_path=(
                f"/manage/admin/cc-pair/{stored.cc_pair_id}/edit/checks"
            ),
        )


class ConnectorEditApplyRequest(EditPlanChoices):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID


class ConnectorEditApplyResponse(BaseModel):
    cc_pair_id: int
    plan_id: UUID
    # The steps that ran or are requested, in apply order.
    steps: list[EditStep]
    # The pair was INVALID and the validation of the new state passed.
    reactivated: bool


class ConnectorEditChecksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_specific_config: dict[str, Any]
    access_type: AccessType
    # None keeps the pair's credential.
    credential_id: int | None = None
    rerun: DraftRerunMode = DraftRerunMode.NONE
