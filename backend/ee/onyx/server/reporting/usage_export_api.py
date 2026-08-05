from collections.abc import Generator
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.db.usage_export import (
    UsageReportMetadata,
    get_all_usage_reports,
    get_usage_report_data,
    usage_report_id_in_use,
)
from onyx.auth.permissions import require_permission
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.file_store.constants import STANDARD_CHUNK_SIZE
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()


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
            raise HTTPException(status_code=400, detail=str(e))

    if params.report_id and usage_report_id_in_use(db_session, params.report_id):
        raise HTTPException(
            status_code=409,
            detail=f"report_id {params.report_id} is already in use",
        )

    tenant_id = get_current_tenant_id()
    client_app.send_task(
        OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK,
        kwargs={
            "tenant_id": tenant_id,
            "user_id": str(user.id) if user else None,
            "period_from": params.period_from,
            "period_to": params.period_to,
            "report_id": str(params.report_id) if params.report_id else None,
        },
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
        raise HTTPException(status_code=404, detail=str(e))

    def iterfile() -> Generator[bytes, None, None]:
        while True:
            chunk = file.read(STANDARD_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        content=iterfile(),
        media_type="application/zip",
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
        raise HTTPException(status_code=404, detail=str(e))
