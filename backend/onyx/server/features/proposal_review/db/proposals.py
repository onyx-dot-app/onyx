"""DB operations for proposal state records."""

from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import Session

from onyx.server.features.proposal_review.db.models import ProposalReviewProposal
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_proposal(
    proposal_id: UUID,
    tenant_id: str,
    db_session: Session,
) -> ProposalReviewProposal | None:
    """Get a proposal by its ID."""
    return (
        db_session.query(ProposalReviewProposal)
        .filter(
            ProposalReviewProposal.id == proposal_id,
            ProposalReviewProposal.tenant_id == tenant_id,
        )
        .one_or_none()
    )


def get_proposal_by_document_id(
    document_id: str,
    tenant_id: str,
    db_session: Session,
) -> ProposalReviewProposal | None:
    """Get a proposal by its linked document ID."""
    return (
        db_session.query(ProposalReviewProposal)
        .filter(
            ProposalReviewProposal.document_id == document_id,
            ProposalReviewProposal.tenant_id == tenant_id,
        )
        .one_or_none()
    )


def get_or_create_proposal(
    document_id: str,
    tenant_id: str,
    db_session: Session,
) -> ProposalReviewProposal:
    """Get or lazily create a proposal state record for a document.

    This is the primary entry point — the proposal record is created on first
    interaction, not when the Jira ticket is ingested.
    """
    proposal = get_proposal_by_document_id(document_id, tenant_id, db_session)
    if proposal:
        return proposal

    proposal = ProposalReviewProposal(
        document_id=document_id,
        tenant_id=tenant_id,
    )
    db_session.add(proposal)
    db_session.flush()
    logger.info(f"Lazily created proposal {proposal.id} for document {document_id}")
    return proposal


def list_proposals(
    tenant_id: str,
    db_session: Session,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ProposalReviewProposal]:
    """List proposals for a tenant with optional status filter."""
    query = (
        db_session.query(ProposalReviewProposal)
        .filter(ProposalReviewProposal.tenant_id == tenant_id)
        .order_by(desc(ProposalReviewProposal.updated_at))
    )
    if status:
        query = query.filter(ProposalReviewProposal.status == status)
    return query.offset(offset).limit(limit).all()


def count_proposals(
    tenant_id: str,
    db_session: Session,
    status: str | None = None,
) -> int:
    """Count proposals for a tenant."""
    query = db_session.query(ProposalReviewProposal).filter(
        ProposalReviewProposal.tenant_id == tenant_id
    )
    if status:
        query = query.filter(ProposalReviewProposal.status == status)
    return query.count()


def update_proposal_status(
    proposal_id: UUID,
    tenant_id: str,
    status: str,
    db_session: Session,
) -> ProposalReviewProposal | None:
    """Update a proposal's status."""
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
    proposal.status = status
    proposal.updated_at = datetime.now(timezone.utc)
    db_session.flush()
    logger.info(f"Updated proposal {proposal_id} status to {status}")
    return proposal
