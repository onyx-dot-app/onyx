"""API endpoints for review triggers, status, and findings."""

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
from onyx.server.features.proposal_review.api.models import AuditLogEntry
from onyx.server.features.proposal_review.api.models import FindingResponse
from onyx.server.features.proposal_review.api.models import ReviewRunResponse
from onyx.server.features.proposal_review.api.models import ReviewRunTriggerRequest
from onyx.server.features.proposal_review.db import decisions as decisions_db
from onyx.server.features.proposal_review.db import findings as findings_db
from onyx.server.features.proposal_review.db import proposals as proposals_db
from onyx.server.features.proposal_review.db import rulesets as rulesets_db
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter()


@router.post(
    "/proposals/{proposal_id}/review",
    status_code=201,
)
def trigger_review(
    proposal_id: UUID,
    request: ReviewRunTriggerRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ReviewRunResponse:
    """Trigger a new review run for a proposal.

    Creates a ReviewRun record and returns it. No Celery dispatch yet --
    the engine will be wired in Workstream 3.
    """
    tenant_id = get_current_tenant_id()

    # Verify proposal exists
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

    # Verify ruleset exists and count active rules
    ruleset = rulesets_db.get_ruleset(request.ruleset_id, tenant_id, db_session)
    if not ruleset:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Ruleset not found")

    active_rule_count = rulesets_db.count_active_rules(request.ruleset_id, db_session)
    if active_rule_count == 0:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Ruleset has no active rules",
        )

    # Update proposal status to IN_REVIEW
    proposals_db.update_proposal_status(proposal_id, tenant_id, "IN_REVIEW", db_session)

    # Create the review run record
    run = findings_db.create_review_run(
        proposal_id=proposal_id,
        ruleset_id=request.ruleset_id,
        triggered_by=user.id,
        total_rules=active_rule_count,
        db_session=db_session,
    )

    # Create audit log entry
    decisions_db.create_audit_log(
        proposal_id=proposal_id,
        action="review_triggered",
        user_id=user.id,
        details={
            "review_run_id": str(run.id),
            "ruleset_id": str(request.ruleset_id),
            "total_rules": active_rule_count,
        },
        db_session=db_session,
    )

    db_session.commit()
    logger.info(
        f"Review triggered for proposal {proposal_id} "
        f"with ruleset {request.ruleset_id} ({active_rule_count} rules)"
    )

    # Dispatch Celery task to run the review asynchronously
    from onyx.server.features.proposal_review.engine.review_engine import (
        run_proposal_review,
    )

    run_proposal_review.apply_async(args=[str(run.id), tenant_id], expires=3600)

    return ReviewRunResponse.from_model(run)


@router.get(
    "/proposals/{proposal_id}/review-status",
)
def get_review_status(
    proposal_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> ReviewRunResponse:
    """Get the status of the latest review run for a proposal."""
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

    run = findings_db.get_latest_review_run(proposal_id, db_session)
    if not run:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "No review runs found")

    return ReviewRunResponse.from_model(run)


@router.get(
    "/proposals/{proposal_id}/findings",
)
def get_findings(
    proposal_id: UUID,
    review_run_id: UUID | None = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> list[FindingResponse]:
    """Get findings for a proposal.

    If review_run_id is not specified, returns findings from the latest run.
    """
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

    # If no run specified, get the latest
    if review_run_id is None:
        run = findings_db.get_latest_review_run(proposal_id, db_session)
        if not run:
            return []
        review_run_id = run.id

    results = findings_db.list_findings_by_run(review_run_id, db_session)
    return [FindingResponse.from_model(f) for f in results]


@router.get(
    "/proposals/{proposal_id}/audit-log",
)
def get_audit_log(
    proposal_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> list[AuditLogEntry]:
    """Get the audit trail for a proposal."""
    tenant_id = get_current_tenant_id()
    proposal = proposals_db.get_proposal(proposal_id, tenant_id, db_session)
    if not proposal:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Proposal not found")

    entries = decisions_db.list_audit_log(proposal_id, db_session)
    return [AuditLogEntry.from_model(e) for e in entries]
