"""DB operations for checklist import jobs."""

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
        f"Created import job {job.id} for ruleset {ruleset_id} "
        f"(file: {source_filename})"
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
