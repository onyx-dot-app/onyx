"""DB operations for review runs and findings."""

from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.server.features.proposal_review.db.models import ProposalReviewFinding
from onyx.server.features.proposal_review.db.models import ProposalReviewRun
from onyx.utils.logger import setup_logger

logger = setup_logger()


# =============================================================================
# Review Runs
# =============================================================================


def create_review_run(
    proposal_id: UUID,
    ruleset_id: UUID,
    triggered_by: UUID,
    total_rules: int,
    db_session: Session,
) -> ProposalReviewRun:
    """Create a new review run record."""
    run = ProposalReviewRun(
        proposal_id=proposal_id,
        ruleset_id=ruleset_id,
        triggered_by=triggered_by,
        total_rules=total_rules,
    )
    db_session.add(run)
    db_session.flush()
    logger.info(
        f"Created review run {run.id} for proposal {proposal_id} "
        f"with {total_rules} rules"
    )
    return run


def get_review_run(
    run_id: UUID,
    db_session: Session,
) -> ProposalReviewRun | None:
    """Get a review run by ID."""
    return (
        db_session.query(ProposalReviewRun)
        .filter(ProposalReviewRun.id == run_id)
        .one_or_none()
    )


def get_latest_review_run(
    proposal_id: UUID,
    db_session: Session,
) -> ProposalReviewRun | None:
    """Get the most recent review run for a proposal."""
    return (
        db_session.query(ProposalReviewRun)
        .filter(ProposalReviewRun.proposal_id == proposal_id)
        .order_by(desc(ProposalReviewRun.created_at))
        .first()
    )


def list_review_runs_by_proposal(
    proposal_id: UUID,
    db_session: Session,
    limit: int = 20,
) -> list[ProposalReviewRun]:
    """List review runs for a proposal, most recent first."""
    return (
        db_session.query(ProposalReviewRun)
        .filter(ProposalReviewRun.proposal_id == proposal_id)
        .order_by(desc(ProposalReviewRun.created_at))
        .limit(limit)
        .all()
    )


# =============================================================================
# Findings
# =============================================================================


def create_finding(
    proposal_id: UUID,
    rule_id: UUID,
    review_run_id: UUID,
    verdict: str,
    db_session: Session,
    confidence: str | None = None,
    evidence: str | None = None,
    explanation: str | None = None,
    suggested_action: str | None = None,
    llm_model: str | None = None,
    llm_tokens_used: int | None = None,
) -> ProposalReviewFinding:
    """Create a new finding."""
    finding = ProposalReviewFinding(
        proposal_id=proposal_id,
        rule_id=rule_id,
        review_run_id=review_run_id,
        verdict=verdict,
        confidence=confidence,
        evidence=evidence,
        explanation=explanation,
        suggested_action=suggested_action,
        llm_model=llm_model,
        llm_tokens_used=llm_tokens_used,
    )
    db_session.add(finding)
    db_session.flush()
    logger.info(
        f"Created finding {finding.id} verdict={verdict} for proposal {proposal_id}"
    )
    return finding


def get_finding(
    finding_id: UUID,
    db_session: Session,
) -> ProposalReviewFinding | None:
    """Get a finding by ID with its rule eagerly loaded."""
    return (
        db_session.query(ProposalReviewFinding)
        .filter(ProposalReviewFinding.id == finding_id)
        .options(
            selectinload(ProposalReviewFinding.rule),
        )
        .one_or_none()
    )


def list_findings_by_proposal(
    proposal_id: UUID,
    db_session: Session,
    review_run_id: UUID | None = None,
) -> list[ProposalReviewFinding]:
    """List findings for a proposal, optionally filtered to a specific run."""
    query = (
        db_session.query(ProposalReviewFinding)
        .filter(ProposalReviewFinding.proposal_id == proposal_id)
        .options(
            selectinload(ProposalReviewFinding.rule),
        )
        .order_by(ProposalReviewFinding.created_at)
    )
    if review_run_id:
        query = query.filter(ProposalReviewFinding.review_run_id == review_run_id)
    return query.all()


def list_findings_by_run(
    review_run_id: UUID,
    db_session: Session,
) -> list[ProposalReviewFinding]:
    """List all findings for a specific review run."""
    return (
        db_session.query(ProposalReviewFinding)
        .filter(ProposalReviewFinding.review_run_id == review_run_id)
        .options(
            selectinload(ProposalReviewFinding.rule),
        )
        .order_by(ProposalReviewFinding.created_at)
        .all()
    )


def get_failed_findings_for_run(
    review_run_id: UUID,
    db_session: Session,
) -> list[ProposalReviewFinding]:
    """Get findings that failed due to system errors (LLM timeout, etc.).

    Error findings are created by _save_error_finding and are identifiable
    by having no LLM metadata (the call never completed successfully).
    """
    return (
        db_session.query(ProposalReviewFinding)
        .filter(
            ProposalReviewFinding.review_run_id == review_run_id,
            ProposalReviewFinding.verdict == "NEEDS_REVIEW",
            ProposalReviewFinding.llm_model.is_(None),
            ProposalReviewFinding.llm_tokens_used.is_(None),
        )
        .all()
    )


def delete_findings(
    finding_ids: list[UUID],
    db_session: Session,
) -> int:
    """Delete findings by ID. Returns the number deleted."""
    if not finding_ids:
        return 0
    count = (
        db_session.query(ProposalReviewFinding)
        .filter(ProposalReviewFinding.id.in_(finding_ids))
        .delete(synchronize_session="fetch")
    )
    return count
