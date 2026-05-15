from celery import shared_task

from ee.onyx.db.license import get_license
from ee.onyx.utils.license import verify_license_signature
from ee.onyx.utils.license_expiry import ExpiryWarningStage
from ee.onyx.utils.license_expiry import get_expiry_warning_stage
from ee.onyx.utils.license_notifications import notify_admins_for_stage
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.CHECK_LICENSE_EXPIRY_NOTIFICATIONS,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def check_license_expiry_notifications_task(*, tenant_id: str) -> None:  # noqa: ARG001
    if MULTI_TENANT:
        return

    with get_session_with_current_tenant() as db_session:
        license_record = get_license(db_session)
        if not license_record:
            return

        try:
            payload = verify_license_signature(license_record.license_data)
        except ValueError:
            logger.exception(
                "Failed to verify license during expiry-notification check"
            )
            return

        stage = get_expiry_warning_stage(payload.expires_at)
        if stage == ExpiryWarningStage.NONE:
            return

        notify_admins_for_stage(
            db_session=db_session,
            stage=stage,
            expires_at=payload.expires_at,
        )
