from typing import List
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.orm import Session
from starlette.background import BackgroundTasks

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.background.task_utils import drain_processing_loop
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import (
    CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.db.models import User
from onyx.db.projects import (
    CategorizedFilesResult,
    check_project_ownership,
    create_user_files,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def upload_files_to_user_files_with_indexing(
    files: List[UploadFile],
    project_id: int | None,
    user: User,
    temp_id_map: dict[str, str] | None,
    db_session: Session,
    background_tasks: BackgroundTasks | None = None,
    incognito_session_id: UUID | None = None,
    temp_ids: list[str] | None = None,
) -> CategorizedFilesResult:
    if project_id is not None and user is not None:
        if not check_project_ownership(project_id, user.id, db_session):
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Project not found")

    categorized_files_result = create_user_files(
        files,
        project_id,
        user,
        db_session,
        temp_id_map=temp_id_map,
        incognito_session_id=incognito_session_id,
        temp_ids=temp_ids,
    )
    user_files = categorized_files_result.user_files
    rejected_files = categorized_files_result.rejected_files
    id_to_temp_id = categorized_files_result.id_to_temp_id
    indexable_files = categorized_files_result.indexable_files
    # Trigger per-file processing immediately for the current tenant
    tenant_id = get_current_tenant_id()
    for rejected_file in rejected_files:
        logger.warning(
            "File %s rejected for %s", rejected_file.filename, rejected_file.reason
        )

    if DISABLE_VECTOR_DB and background_tasks is not None:
        background_tasks.add_task(drain_processing_loop, tenant_id)
        for user_file in indexable_files:
            logger.info(
                "Queued in-process processing for user_file_id=%s", user_file.id
            )
    else:
        for user_file in indexable_files:
            task = client_app.send_task(
                OnyxCeleryTask.PROCESS_SINGLE_USER_FILE,
                kwargs={"user_file_id": user_file.id, "tenant_id": tenant_id},
                queue=OnyxCeleryQueues.USER_FILE_PROCESSING,
                priority=OnyxCeleryPriority.HIGH,
                expires=CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
            )
            logger.info(
                "Triggered indexing for user_file_id=%s with task_id=%s",
                user_file.id,
                task.id,
            )

    return CategorizedFilesResult(
        user_files=user_files,
        rejected_files=rejected_files,
        id_to_temp_id=id_to_temp_id,
    )
