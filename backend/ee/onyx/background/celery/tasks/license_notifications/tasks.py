import requests
from celery import shared_task
from sqlalchemy.orm import Session

from ee.onyx.db.license import get_license
from ee.onyx.server.license.models import LicensePayload, LicenseSource
from ee.onyx.utils.license import (
    LicenseNotStoredError,
    LicenseRejectedError,
    reclaim_license_from_control_plane,
    verify_license_signature,
)
from ee.onyx.utils.license_expiry import ExpiryWarningStage, get_expiry_warning_stage
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

        stage = get_expiry_warning_stage(
            payload.expires_at, payload.ends_with_trial, payload.self_renewing
        )
        if stage == ExpiryWarningStage.NONE:
            return

        renewal_error: str | None = None
        if stage == ExpiryWarningStage.GRACE:
            payload, renewal_error = _sync_expired_license(db_session, payload)
            if renewal_error is None:
                # The renewal landed, so there is nothing left to warn about.
                return
            stage = get_expiry_warning_stage(
                payload.expires_at, payload.ends_with_trial, payload.self_renewing
            )
            if stage == ExpiryWarningStage.NONE:
                return

        notify_admins_for_stage(
            db_session=db_session,
            stage=stage,
            expires_at=payload.expires_at,
            renewal_error=renewal_error,
            is_trial=payload.ends_with_trial,
        )


def _sync_expired_license(
    db_session: Session, stored: LicensePayload
) -> tuple[LicensePayload, str | None]:
    """Pull the renewal an expired instance is waiting on.

    A renewal, if one happened, lands exactly when grace begins, so this runs
    where the stage is already computed rather than on a poll of its own. Returns the
    license now in force and why it is still expired, or None once renewed.

    A sales-issued license has no control plane to ask.
    """
    if stored.source == LicenseSource.MANUAL_UPLOAD:
        return stored, "This license is managed by Onyx sales. Contact your rep."

    try:
        renewed = reclaim_license_from_control_plane(db_session)
    except LicenseRejectedError as e:
        return stored, f"{e}."
    except LicenseNotStoredError:
        return stored, "No license is installed on this instance."
    except (requests.RequestException, ValueError) as e:
        logger.warning("License renewal check failed: %s", e)
        return stored, "Onyx could not be reached to check for a renewal."

    if renewed.issued_at <= stored.issued_at:
        # Same license back: the subscription did not renew. Whether that is a
        # declined card or a cancellation is only knowable from billing.
        return stored, "No renewed license is available for your subscription."
    return renewed, None
