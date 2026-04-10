"""API endpoints for per-finding decisions, proposal decisions, and Jira sync."""

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.features.proposal_review.api.models import FindingDecisionCreate
from onyx.server.features.proposal_review.api.models import FindingDecisionResponse
from onyx.server.features.proposal_review.api.models import JiraSyncResponse
from onyx.server.features.proposal_review.api.models import ProposalDecisionCreate
from onyx.server.features.proposal_review.api.models import ProposalDecisionResponse
from onyx.server.features.proposal_review.db import decisions as decisions_db
from onyx.server.features.proposal_review.db import findings as findings_db
from onyx.server.features.proposal_review.db import proposals as proposals_db
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter()


@router.post(
    "/findings/{finding_id}/decision",
    response_model=FindingDecisionResponse,
)
def record_finding_decision(
    finding_id: UUID,
    request: FindingDecisionCreate,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> FindingDecisionResponse:
    """Record or update a decision on a finding (upsert)."""
    tenant_id = get_current_tenant_id()

    # Verify finding exists
    finding = findings_db.get_finding(finding_id, db_session)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Verify the finding's proposal belongs to the current tenant
    proposal = proposals_db.get_proposal(finding.proposal_id, tenant_id, db_session)
    if not proposal:
        raise HTTPException(status_code=404, detail="Finding not found")

    decision = decisions_db.upsert_finding_decision(
        finding_id=finding_id,
        officer_id=user.id,
        action=request.action,
        notes=request.notes,
        db_session=db_session,
    )

    # Audit log
    decisions_db.create_audit_log(
        proposal_id=finding.proposal_id,
        action="finding_decided",
        user_id=user.id,
        details={
            "finding_id": str(finding_id),
            "action": request.action,
        },
        db_session=db_session,
    )

    db_session.commit()
    return FindingDecisionResponse.from_model(decision)


@router.post(
    "/proposals/{proposal_id}/decision",
    response_model=ProposalDecisionResponse,
    status_code=201,
)
def record_proposal_decision(
    proposal_id: UUID,
    request: ProposalDecisionCreate,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ProposalDecisionResponse:
    """Record a final decision on a proposal."""
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    # Map decision to proposal status
    status_map = {
        "APPROVED": "APPROVED",
        "CHANGES_REQUESTED": "CHANGES_REQUESTED",
        "REJECTED": "REJECTED",
    }
    new_status = status_map.get(request.decision)
    if not new_status:
        raise HTTPException(
            status_code=400,
            detail="decision must be APPROVED, CHANGES_REQUESTED, or REJECTED",
        )

    # Update proposal status
    proposals_db.update_proposal_status(proposal_id, tenant_id, new_status, db_session)

    # Create the decision record
    decision = decisions_db.create_proposal_decision(
        proposal_id=proposal_id,
        officer_id=user.id,
        decision=request.decision,
        notes=request.notes,
        db_session=db_session,
    )

    # Audit log
    decisions_db.create_audit_log(
        proposal_id=proposal_id,
        action="decision_submitted",
        user_id=user.id,
        details={
            "decision_id": str(decision.id),
            "decision": request.decision,
        },
        db_session=db_session,
    )

    db_session.commit()
    return ProposalDecisionResponse.from_model(decision)


@router.post(
    "/proposals/{proposal_id}/sync-jira",
    response_model=JiraSyncResponse,
)
def sync_jira(
    proposal_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> JiraSyncResponse:
    """Sync the latest proposal decision to Jira.

    Dispatches a Celery task that performs 3 Jira API operations:
    1. Update custom fields (decision, completion %)
    2. Transition the issue to the appropriate column
    3. Post a structured review summary comment
    """
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    latest_decision = decisions_db.get_latest_proposal_decision(proposal_id, db_session)
    if not latest_decision:
        raise HTTPException(
            status_code=400,
            detail="No decision to sync -- record a proposal decision first",
        )

    if latest_decision.jira_synced:
        return JiraSyncResponse(
            success=True,
            message="Decision already synced to Jira",
        )

    # Dispatch Celery task for Jira sync
    from onyx.server.features.proposal_review.engine.review_engine import (
        sync_decision_to_jira,
    )

    sync_decision_to_jira.delay(str(proposal_id), tenant_id)

    # Audit log
    decisions_db.create_audit_log(
        proposal_id=proposal_id,
        action="jira_sync_dispatched",
        user_id=user.id,
        details={"decision_id": str(latest_decision.id)},
        db_session=db_session,
    )

    db_session.commit()
    return JiraSyncResponse(
        success=True,
        message="Jira sync task dispatched",
    )
