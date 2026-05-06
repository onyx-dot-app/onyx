"""DB operations for checklist import jobs."""

import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.server.features.proposal_review.db.models import ProposalReviewImportJob
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_import_job(
    ruleset_id: UUID,
    tenant_id: str,
    source_filename: str,
    extracted_text: str,
    db_session: Session,
) -> ProposalReviewImportJob:
    """Create a new import job record."""
    job = ProposalReviewImportJob(
        ruleset_id=ruleset_id,
        tenant_id=tenant_id,
        source_filename=source_filename,
        extracted_text=extracted_text,
    )
    db_session.add(job)
    db_session.flush()
    logger.info(
        "Created import job %s for ruleset %s (file: %s)",
        job.id,
        ruleset_id,
        source_filename,
    )
    return job


def get_import_job(
    job_id: UUID,
    db_session: Session,
) -> ProposalReviewImportJob | None:
    """Get a single import job by ID."""
    return (
        db_session.query(ProposalReviewImportJob)
        .filter(ProposalReviewImportJob.id == job_id)
        .one_or_none()
    )


def get_active_import_job(
    ruleset_id: UUID,
    db_session: Session,
) -> ProposalReviewImportJob | None:
    """Get the latest PENDING or RUNNING import job for a ruleset, if any."""
    return (
        db_session.query(ProposalReviewImportJob)
        .filter(
            ProposalReviewImportJob.ruleset_id == ruleset_id,
            ProposalReviewImportJob.status.in_(["PENDING", "RUNNING"]),
        )
        .order_by(ProposalReviewImportJob.created_at.desc())
        .first()
    )


def get_dangling_import_jobs(
    db_session: Session,
    stale_threshold_minutes: int = 30,
) -> list[ProposalReviewImportJob]:
    """Return import jobs stuck in PENDING or RUNNING for longer than the threshold."""
    cutoff = datetime.datetime.now(timezone.utc) - datetime.timedelta(
        minutes=stale_threshold_minutes
    )
    return (
        db_session.query(ProposalReviewImportJob)
        .filter(
            ProposalReviewImportJob.status.in_(["PENDING", "RUNNING"]),
            ProposalReviewImportJob.created_at < cutoff,
        )
        .all()
    )


def get_latest_failed_import_job(
    ruleset_id: UUID,
    db_session: Session,
) -> ProposalReviewImportJob | None:
    """Get the most recent FAILED import job for a ruleset, but only if no
    newer COMPLETED or in-progress job exists (i.e. the failure is still
    the latest outcome)."""
    latest = (
        db_session.query(ProposalReviewImportJob)
        .filter(ProposalReviewImportJob.ruleset_id == ruleset_id)
        .order_by(ProposalReviewImportJob.created_at.desc())
        .first()
    )
    if latest and latest.status == "FAILED":
        return latest
    return None


def reset_import_job_for_retry(
    job_id: UUID,
    db_session: Session,
) -> bool:
    """Atomically reset a FAILED import job back to PENDING for re-dispatch.

    Returns True if the row was updated, False if the job was not in FAILED
    state (e.g. a concurrent retry already transitioned it).
    """
    rows = (
        db_session.query(ProposalReviewImportJob)
        .filter(
            ProposalReviewImportJob.id == job_id,
            ProposalReviewImportJob.status == "FAILED",
        )
        .update(
            {
                ProposalReviewImportJob.status: "PENDING",
                ProposalReviewImportJob.error_message: None,
                ProposalReviewImportJob.rules_created: 0,
                ProposalReviewImportJob.completed_at: None,
            },
            synchronize_session="fetch",
        )
    )
    db_session.flush()
    return rows > 0


def mark_import_job_failed(
    job: ProposalReviewImportJob,
    error_message: str,
    db_session: Session,
) -> None:
    """Mark an import job as FAILED with the given error message.

    Flushes but does NOT commit — the caller is responsible for committing
    so that batch operations can be done in a single transaction.
    """
    job.status = "FAILED"
    job.error_message = error_message
    job.completed_at = datetime.datetime.now(timezone.utc)
    db_session.flush()
