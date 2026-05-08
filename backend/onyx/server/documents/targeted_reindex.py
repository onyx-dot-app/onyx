"""Admin endpoints for the targeted-reindex flow.

Two endpoints:

* `POST /manage/admin/indexing/targeted-reindex` — submit error IDs and/or
  doc refs, returns a job id the FE polls.
* `GET  /manage/admin/indexing/targeted-reindex/{job_id}` — current status.

The POST handler validates input, persists the job + per-doc target
rows + per-cc-pair synthetic IndexAttempts, and enqueues the celery
task with the pre-allocated task UUID.
"""

import datetime
from typing import Any

from celery import current_app as celery_app
from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_curator_or_admin_user
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import IndexingStatus
from onyx.db.models import User
from onyx.db.targeted_reindex import count_targets_for_job
from onyx.db.targeted_reindex import create_targeted_reindex_job
from onyx.db.targeted_reindex import get_targeted_reindex_job
from onyx.db.targeted_reindex import MAX_TARGETS_PER_REQUEST
from onyx.db.targeted_reindex import resolve_error_ids_to_targets
from onyx.db.targeted_reindex import TargetSpec
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/manage")


class DocumentTargetRequest(BaseModel):
    cc_pair_id: int
    document_id: str


class TargetedReindexRequest(BaseModel):
    """Either `error_ids` (failure-driven retry) or `targets` (arbitrary
    doc reindex). At least one must be non-empty."""

    error_ids: list[int] | None = None
    targets: list[DocumentTargetRequest] | None = None


class TargetedReindexResponse(BaseModel):
    targeted_reindex_job_id: int
    queued_count: int
    skipped_count: int


class TargetedReindexJobStatusResponse(BaseModel):
    id: int
    status: IndexingStatus
    requested_at: datetime.datetime
    completed_at: datetime.datetime | None
    target_count: int
    resolved_count: int
    still_failing_count: int
    skipped_count: int
    resolved_summary: list[dict[str, Any]]


@router.post("/admin/indexing/targeted-reindex")
def submit_targeted_reindex(
    request: TargetedReindexRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> TargetedReindexResponse:
    error_ids = request.error_ids or []
    target_specs_in: list[TargetSpec] = [
        TargetSpec(cc_pair_id=t.cc_pair_id, document_id=t.document_id)
        for t in (request.targets or [])
    ]

    if not error_ids and not target_specs_in:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Either error_ids or targets must be provided.",
        )

    skipped_from_errors = 0
    if error_ids:
        derived, skipped_from_errors = resolve_error_ids_to_targets(
            db_session, error_ids
        )
        target_specs_in.extend(derived)

    if not target_specs_in:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "No actionable targets after resolving error_ids "
            "(all were already resolved, entity-level, or invalid).",
        )

    if len(target_specs_in) > MAX_TARGETS_PER_REQUEST:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Too many targets: %s > %s."
            % (len(target_specs_in), MAX_TARGETS_PER_REQUEST),
        )

    try:
        result = create_targeted_reindex_job(
            db_session=db_session,
            requested_by_user_id=user.id if user else None,
            targets=target_specs_in,
            upstream_skipped_count=skipped_from_errors,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

    tenant_id = get_current_tenant_id()
    try:
        # Route to the existing PRIMARY queue. The design has the trigger
        # task running on the primary worker that already owns the
        # indexing scheduler. Per-cc-pair fan-out (connector fetch +
        # docprocessing) hands off to the existing docfetching/
        # docprocessing queues from inside the task body.
        celery_app.send_task(
            OnyxCeleryTask.TARGETED_REINDEX_TASK,
            kwargs={
                "targeted_reindex_job_id": result.targeted_reindex_job_id,
                "tenant_id": tenant_id,
            },
            queue=OnyxCeleryQueues.PRIMARY,
            priority=OnyxCeleryPriority.HIGHEST,
            task_id=result.celery_task_id,
        )
    except Exception:
        logger.exception(
            "Failed to enqueue targeted reindex task",
            extra={"job_id": result.targeted_reindex_job_id},
        )
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "Failed to enqueue targeted reindex task.",
        )

    return TargetedReindexResponse(
        targeted_reindex_job_id=result.targeted_reindex_job_id,
        queued_count=result.queued_count,
        skipped_count=result.skipped_count,
    )


@router.get("/admin/indexing/targeted-reindex/{job_id}")
def get_targeted_reindex_status(
    job_id: int,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> TargetedReindexJobStatusResponse:
    job = get_targeted_reindex_job(db_session, job_id)
    if job is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Job not found.")

    return TargetedReindexJobStatusResponse(
        id=job.id,
        status=job.status,
        requested_at=job.requested_at,
        completed_at=job.completed_at,
        target_count=count_targets_for_job(db_session, job.id),
        resolved_count=job.resolved_count,
        still_failing_count=job.still_failing_count,
        skipped_count=job.skipped_count,
        resolved_summary=job.resolved_summary,
    )
