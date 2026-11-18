from collections.abc import Generator
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.db.usage_export import (
    UsageReportMetadata,
    get_all_usage_reports,
    get_usage_report_data,
    register_usage_report_job,
)
from ee.onyx.server.reporting.usage_export_models import (
    USAGE_REPORT_MEDIA_TYPE,
    UsageReportJob,
)
from onyx.auth.permissions import require_permission
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import (
    USER_EXPORT_TASK_EXPIRES,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission, TaskStatus
from onyx.db.models import User
from onyx.db.tasks import fail_task_with_id, get_all_tasks_with_prefix
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.constants import STANDARD_CHUNK_SIZE
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter()


@router.get("/admin/usage-report-jobs")
def fetch_usage_report_jobs(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[UsageReportJob]:
    return [
        UsageReportJob(
            report_id=UUID(task.task_id),
            status=task.status,
            time_created=task.register_time,
        )
        for task in get_all_tasks_with_prefix(
            db_session, OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK
        )
    ]


class GenerateUsageReportParams(BaseModel):
    period_from: str | None = None
    period_to: str | None = None
    report_id: UUID | None = None


@router.post("/admin/usage-report", status_code=204)
def generate_report(
    params: GenerateUsageReportParams,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    # Validate period parameters
    if params.period_from and params.period_to:
        try:
            datetime.fromisoformat(params.period_from)
            datetime.fromisoformat(params.period_to)
        except ValueError as e:
            raise OnyxError(OnyxErrorCode.BAD_REQUEST, str(e))

    report_id = params.report_id or uuid4()
    register_usage_report_job(db_session, report_id)
    tenant_id = get_current_tenant_id()
    try:
        client_app.send_task(
            OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK,
            expires=USER_EXPORT_TASK_EXPIRES,
            queue=OnyxCeleryQueues.PRIMARY,
            task_id=str(report_id),
            kwargs={
                "tenant_id": tenant_id,
                "user_id": str(user.id) if user else None,
                "period_from": params.period_from,
                "period_to": params.period_to,
                "report_id": str(report_id),
            },
        )
    except Exception:
        logger.exception("Failed to send usage report task report_id=%s", report_id)
        fail_task_with_id(db_session, str(report_id), TaskStatus.PENDING)
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "Failed to start the usage report.",
        )

    return None


@router.get("/admin/usage-report/{report_name}")
def read_usage_report(
    report_name: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),  # noqa: ARG001
) -> Response:
    try:
        file = get_usage_report_data(report_name)
    except (ValueError, RuntimeError) as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e))

    def iterfile() -> Generator[bytes, None, None]:
        while True:
            chunk = file.read(STANDARD_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        content=iterfile(),
        media_type=USAGE_REPORT_MEDIA_TYPE,
        headers={"Content-Disposition": f"attachment; filename={report_name}"},
    )


@router.get("/admin/usage-report")
def fetch_usage_reports(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[UsageReportMetadata]:
    try:
        return get_all_usage_reports(db_session)
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e))
