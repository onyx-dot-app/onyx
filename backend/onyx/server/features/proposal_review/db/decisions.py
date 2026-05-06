"""DB operations for finding decisions and proposal decisions.

Finding decisions are stored inline on the ProposalReviewFinding row.
Proposal decisions are stored inline on the ProposalReviewProposal row.
"""

from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.server.features.proposal_review.db.models import ProposalReviewFinding
from onyx.server.features.proposal_review.db.models import ProposalReviewProposal
from onyx.utils.logger import setup_logger

logger = setup_logger()


# =============================================================================
# Per-Finding Decisions (inline on finding row)
# =============================================================================


def upsert_finding_decision(
    finding_id: UUID,
    officer_id: UUID,
    action: str,
    db_session: Session,
    notes: str | None = None,
) -> ProposalReviewFinding:
    """Record or update a decision on a finding.

    The decision fields live directly on the finding row.
    """
    finding = (
        db_session.query(ProposalReviewFinding)
        .filter(ProposalReviewFinding.id == finding_id)
        .one_or_none()
    )
    if not finding:
        raise ValueError(f"Finding {finding_id} not found")

    finding.decision_action = action
    finding.decision_notes = notes
    finding.decision_officer_id = officer_id
    finding.decided_at = datetime.now(timezone.utc)
    db_session.flush()

    logger.info("Recorded decision on finding %s: %s", finding_id, action)
    return finding


# =============================================================================
# Proposal-Level Decisions (inline on proposal row)
# =============================================================================


def update_proposal_decision(
    proposal_id: UUID,
    tenant_id: str,
    officer_id: UUID,
    decision: str,
    db_session: Session,
    notes: str | None = None,
) -> ProposalReviewProposal:
    """Record a final decision on a proposal.

    Overwrites previous decision fields on the proposal row.
    """
    proposal = (
        db_session.query(ProposalReviewProposal)
        .filter(
            ProposalReviewProposal.id == proposal_id,
            ProposalReviewProposal.tenant_id == tenant_id,
        )
        .one_or_none()
    )
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")

    proposal.status = decision
    proposal.decision_notes = notes
    proposal.decision_officer_id = officer_id
    proposal.decision_at = datetime.now(timezone.utc)
    proposal.jira_synced = False
    proposal.jira_synced_at = None
    proposal.updated_at = datetime.now(timezone.utc)
    db_session.flush()

    logger.info("Recorded proposal decision %s for proposal %s", decision, proposal_id)
    return proposal


def mark_proposal_jira_synced(
    proposal_id: UUID,
    tenant_id: str,
    db_session: Session,
) -> ProposalReviewProposal | None:
    """Mark a proposal's decision as synced to Jira."""
    proposal = (
        db_session.query(ProposalReviewProposal)
        .filter(
            ProposalReviewProposal.id == proposal_id,
            ProposalReviewProposal.tenant_id == tenant_id,
        )
        .one_or_none()
    )
    if not proposal:
        return None
    proposal.jira_synced = True
    proposal.jira_synced_at = datetime.now(timezone.utc)
    db_session.flush()
    logger.info("Marked proposal %s as jira_synced", proposal_id)
    return proposal
