"""API endpoints for per-finding decisions, proposal decisions, and Jira sync."""

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.proposal_review.api.models import FindingDecisionCreate
from onyx.server.features.proposal_review.api.models import FindingResponse
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
)
def record_finding_decision(
    finding_id: UUID,
    request: FindingDecisionCreate,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> FindingResponse:
    """Record or update a decision on a finding (upsert)."""
    tenant_id = get_current_tenant_id()

    # Verify finding exists
    finding = findings_db.get_finding(finding_id, db_session)
    if not finding:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Finding not found")

    # Verify the finding's proposal belongs to the current tenant
    proposal = proposals_db.get_proposal(finding.proposal_id, tenant_id, db_session)
    if not proposal:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Finding not found")

    finding = decisions_db.upsert_finding_decision(
        finding_id=finding_id,
        officer_id=user.id,
        action=request.action,
        notes=request.notes,
        db_session=db_session,
    )

    db_session.commit()
    return FindingResponse.from_model(finding)


@router.post(
    "/proposals/{proposal_id}/decision",
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
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

    # Validate decision value
    valid_decisions = {"APPROVED", "CHANGES_REQUESTED", "REJECTED"}
    if request.decision not in valid_decisions:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "decision must be APPROVED, CHANGES_REQUESTED, or REJECTED",
        )

    proposal = decisions_db.update_proposal_decision(
        proposal_id=proposal_id,
        tenant_id=tenant_id,
        officer_id=user.id,
        decision=request.decision,
        notes=request.notes,
        db_session=db_session,
    )

    db_session.commit()
    return ProposalDecisionResponse.from_proposal(proposal)


@router.post(
    "/proposals/{proposal_id}/sync-jira",
)
def sync_jira(
    proposal_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
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
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

    if not proposal.decision_at:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "No decision to sync -- record a proposal decision first",
        )

    if proposal.jira_synced:
        return JiraSyncResponse(
            success=True,
            message="Decision already synced to Jira",
        )

    # Dispatch Celery task via the client app (has Redis broker configured)
    from onyx.background.celery.versioned_apps.client import app as celery_app

    celery_app.send_task(
        "sync_decision_to_jira",
        args=[str(proposal_id), tenant_id],
        expires=300,
    )

    db_session.commit()
    return JiraSyncResponse(
        success=True,
        message="Jira sync task dispatched",
    )
