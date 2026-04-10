"""DB operations for finding decisions and proposal decisions."""

from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import Session

from onyx.server.features.proposal_review.db.models import ProposalReviewAuditLog
from onyx.server.features.proposal_review.db.models import ProposalReviewDecision
from onyx.server.features.proposal_review.db.models import (
    ProposalReviewProposalDecision,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


# =============================================================================
# Per-Finding Decisions (upsert — one decision per finding)
# =============================================================================


def upsert_finding_decision(
    finding_id: UUID,
    officer_id: UUID,
    action: str,
    db_session: Session,
    notes: str | None = None,
) -> ProposalReviewDecision:
    """Create or update a decision on a finding.

    There is a UNIQUE constraint on finding_id, so this is an upsert.
    """
    existing = (
        db_session.query(ProposalReviewDecision)
        .filter(ProposalReviewDecision.finding_id == finding_id)
        .one_or_none()
    )

    if existing:
        existing.officer_id = officer_id
        existing.action = action
        existing.notes = notes
        existing.updated_at = datetime.now(timezone.utc)
        db_session.flush()
        logger.info(f"Updated decision on finding {finding_id} to {action}")
        return existing

    decision = ProposalReviewDecision(
        finding_id=finding_id,
        officer_id=officer_id,
        action=action,
        notes=notes,
    )
    db_session.add(decision)
    db_session.flush()
    logger.info(f"Created decision {decision.id} on finding {finding_id}")
    return decision


def get_finding_decision(
    finding_id: UUID,
    db_session: Session,
) -> ProposalReviewDecision | None:
    """Get the decision for a finding."""
    return (
        db_session.query(ProposalReviewDecision)
        .filter(ProposalReviewDecision.finding_id == finding_id)
        .one_or_none()
    )


# =============================================================================
# Proposal-Level Decisions
# =============================================================================


def create_proposal_decision(
    proposal_id: UUID,
    officer_id: UUID,
    decision: str,
    db_session: Session,
    notes: str | None = None,
) -> ProposalReviewProposalDecision:
    """Create a final decision on a proposal."""
    pd = ProposalReviewProposalDecision(
        proposal_id=proposal_id,
        officer_id=officer_id,
        decision=decision,
        notes=notes,
    )
    db_session.add(pd)
    db_session.flush()
    logger.info(
        f"Created proposal decision {pd.id} ({decision}) for proposal {proposal_id}"
    )
    return pd


def get_latest_proposal_decision(
    proposal_id: UUID,
    db_session: Session,
) -> ProposalReviewProposalDecision | None:
    """Get the most recent decision for a proposal."""
    return (
        db_session.query(ProposalReviewProposalDecision)
        .filter(ProposalReviewProposalDecision.proposal_id == proposal_id)
        .order_by(desc(ProposalReviewProposalDecision.created_at))
        .first()
    )


def mark_decision_jira_synced(
    decision_id: UUID,
    db_session: Session,
) -> ProposalReviewProposalDecision | None:
    """Mark a proposal decision as synced to Jira."""
    pd = (
        db_session.query(ProposalReviewProposalDecision)
        .filter(ProposalReviewProposalDecision.id == decision_id)
        .one_or_none()
    )
    if not pd:
        return None
    pd.jira_synced = True
    pd.jira_synced_at = datetime.now(timezone.utc)
    db_session.flush()
    logger.info(f"Marked proposal decision {decision_id} as jira_synced")
    return pd


# =============================================================================
# Audit Log
# =============================================================================


def create_audit_log(
    proposal_id: UUID,
    action: str,
    db_session: Session,
    user_id: UUID | None = None,
    details: dict | None = None,
) -> ProposalReviewAuditLog:
    """Create an audit log entry."""
    entry = ProposalReviewAuditLog(
        proposal_id=proposal_id,
        user_id=user_id,
        action=action,
        details=details,
    )
    db_session.add(entry)
    db_session.flush()
    return entry


def list_audit_log(
    proposal_id: UUID,
    db_session: Session,
) -> list[ProposalReviewAuditLog]:
    """List audit log entries for a proposal, newest first."""
    return (
        db_session.query(ProposalReviewAuditLog)
        .filter(ProposalReviewAuditLog.proposal_id == proposal_id)
        .order_by(desc(ProposalReviewAuditLog.created_at))
        .all()
    )
