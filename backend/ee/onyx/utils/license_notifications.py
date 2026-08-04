"""License-expiry tiered notification orchestration.

Drives email + in-app notification side effects. Idempotency is enforced
through the existing `notification` unique index
`(user_id, notif_type, COALESCE(additional_data, '{}'::jsonb))`. Pre-existing
admins for a given (stage, expires_at[, sent_date]) tuple are skipped, and only
freshly-notified admins receive an email.
"""

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ee.onyx.db.license import get_license
from ee.onyx.utils.license import verify_license_signature
from ee.onyx.utils.license_expiry import (
    ExpiryWarningStage,
    get_expiry_warning_stage,
    get_grace_days_remaining,
)
from onyx.auth.email_utils import build_html_email, send_email
from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import EMAIL_CONFIGURED
from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME, NotificationType
from onyx.db.models import User
from onyx.db.notification import batch_create_notifications
from onyx.db.users import get_active_admin_users
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def _build_trial_copy(
    stage: ExpiryWarningStage, expires_str: str, grace_days_remaining: int
) -> tuple[str, str, str]:
    """Trial-end wording for the same stages, since a trial reaching its end
    is a subscription starting rather than access being lost."""
    if stage == ExpiryWarningStage.GRACE:
        return (
            f"Onyx trial ended. {grace_days_remaining} grace days remaining",
            f"Your trial ended on {expires_str} and billing has not started. "
            f"You have {grace_days_remaining} day(s) of access remaining. Check "
            "your payment method in Plans & Billing to keep Onyx running.",
            f"Onyx trial ended. {grace_days_remaining} grace days remaining",
        )
    when = (
        "within 24 hours" if stage == ExpiryWarningStage.T_1D else f"on {expires_str}"
    )
    return (
        f"Onyx trial ends {expires_str}",
        f"Your trial ends {when} and billing begins then. Visit Plans & "
        "Billing to change your plan or cancel.",
        f"Your Onyx trial ends {expires_str}",
    )


def _build_copy(
    stage: ExpiryWarningStage,
    expires_at: datetime,
    grace_days_remaining: int,
    renewal_error: str | None = None,
    is_trial: bool = False,
) -> tuple[str, str, str]:
    """Returns (banner_title, banner_description, email_subject)."""
    if stage == ExpiryWarningStage.NONE:
        raise ValueError(f"Unsupported stage for notification copy: {stage}")
    expires_str = expires_at.strftime("%Y-%m-%d")
    if renewal_error and is_trial:
        return (
            "Onyx could not start your subscription",
            f"Your trial ended on {expires_str} and billing could not start: "
            f"{renewal_error} You have {grace_days_remaining} day(s) of grace "
            "access remaining.",
            "Action required: Onyx could not start your subscription",
        )
    if renewal_error:
        return (
            "Onyx could not renew your license",
            f"Your license expired on {expires_str} and the automatic renewal "
            f"failed: {renewal_error} You have {grace_days_remaining} day(s) of "
            "grace access remaining.",
            "Action required: Onyx license renewal failed",
        )
    if is_trial:
        return _build_trial_copy(stage, expires_str, grace_days_remaining)
    if stage == ExpiryWarningStage.T_30D:
        return (
            f"Onyx license expires {expires_str}",
            "Your license will expire in approximately 30 days. Contact your "
            "Onyx representative to renew.",
            "Action required: Onyx license expires in ~30 days",
        )
    if stage == ExpiryWarningStage.T_14D:
        return (
            f"Onyx license expires {expires_str}",
            "Your license will expire in approximately 2 weeks. Renewal must "
            "be completed soon to avoid service interruption.",
            "Action required: Onyx license expires in ~2 weeks",
        )
    if stage == ExpiryWarningStage.T_1D:
        return (
            f"Onyx license expires tomorrow ({expires_str})",
            "Your license expires within 24 hours. Renew immediately to avoid "
            "service interruption.",
            "URGENT: Onyx license expires within 24 hours",
        )
    if stage == ExpiryWarningStage.GRACE:
        return (
            f"Onyx license expired. {grace_days_remaining} grace days remaining",
            f"Your license expired on {expires_str}. You have "
            f"{grace_days_remaining} day(s) of grace access remaining before "
            "the instance is gated. Renew now.",
            f"Onyx license expired. {grace_days_remaining} grace days remaining",
        )
    raise ValueError(f"Unsupported stage for notification copy: {stage}")


def _send_email_for_stage(
    user_email: str, subject: str, heading: str, message: str
) -> None:
    if not EMAIL_CONFIGURED:
        logger.warning(
            "Email not configured, skipping license expiry email to %s", user_email
        )
        return
    html_body = build_html_email(
        application_name=ONYX_DEFAULT_APPLICATION_NAME,
        heading=heading,
        message=message,
    )
    text_body = f"{heading}\n\n{message}"
    try:
        send_email(user_email, subject, html_body, text_body)
    except Exception:
        logger.exception("Failed to send license expiry email to %s", user_email)


def _build_additional_data(
    stage: ExpiryWarningStage,
    expires_at: datetime,
    today: date,
    renewal_failed: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "stage": stage.value,
        "expires_at": expires_at.isoformat(),
    }
    if renewal_failed:
        # Its own dedup key, so a failure notice does not collapse into that
        # day's ordinary grace reminder and get silently dropped.
        data["renewal_failed"] = True
    if stage == ExpiryWarningStage.GRACE:
        # Grace period sends one notification per UTC date so admins are
        # reminded daily until they renew.
        data["sent_date"] = today.isoformat()
    return data


def notify_admins_for_stage(
    db_session: Session,
    stage: ExpiryWarningStage,
    expires_at: datetime,
    renewal_error: str | None = None,
    is_trial: bool = False,
) -> None:
    """Create in-app notifications + send emails for admins not already notified.

    renewal_error replaces the copy with why the automatic renewal failed, so an
    admin is told to fix billing rather than to renew something Onyx already
    tried to renew for them.

    is_trial reframes the same stages around a trial ending, so a customer two
    weeks into a trial is not told their access is about to be cut off.
    """
    if stage == ExpiryWarningStage.NONE:
        return

    today = datetime.now(timezone.utc).date()
    admins = get_active_admin_users(db_session)
    if not admins:
        logger.warning("No active admins found to notify for license stage %s", stage)
        return

    additional_data = _build_additional_data(
        stage, expires_at, today, renewal_failed=bool(renewal_error)
    )
    grace_days = get_grace_days_remaining(expires_at)
    title, description, email_subject = _build_copy(
        stage, expires_at, grace_days, renewal_error, is_trial
    )

    inserted_admin_ids = batch_create_notifications(
        user_ids=[a.id for a in admins],
        notif_type=NotificationType.LICENSE_EXPIRY_WARNING,
        db_session=db_session,
        title=title,
        description=description,
        additional_data=additional_data,
    )
    if not inserted_admin_ids:
        return

    admin_by_id = {admin.id: admin for admin in admins}
    for admin_id in inserted_admin_ids:
        admin = admin_by_id.get(admin_id)
        if admin is not None and admin.email:
            _send_email_for_stage(
                user_email=admin.email,
                subject=email_subject,
                heading=title,
                message=description,
            )

    logger.info(
        "License expiry notifications sent: stage=%s admins=%d date=%s",
        stage.value,
        len(inserted_admin_ids),
        today.isoformat(),
    )


def ensure_license_expiry_notification_for_user(
    user: User,
    db_session: Session,
) -> None:
    """On-read fallback: materialize the requesting admin's in-app notification
    for the current expiry stage so the banner appears immediately instead of
    waiting for the once-daily task. Idempotent via the notification unique
    index; never emails (the daily task owns email + all-admin fan-out)."""
    if MULTI_TENANT or user.role != UserRole.ADMIN:
        return

    license_record = get_license(db_session)
    if not license_record:
        return
    try:
        payload = verify_license_signature(license_record.license_data)
    except ValueError:
        logger.exception("Failed to verify license during on-read notification ensure")
        return

    stage = get_expiry_warning_stage(
        payload.expires_at, payload.ends_with_trial, payload.self_renewing
    )
    if stage == ExpiryWarningStage.NONE:
        return

    today = datetime.now(timezone.utc).date()
    additional_data = _build_additional_data(stage, payload.expires_at, today)
    grace_days = get_grace_days_remaining(payload.expires_at)
    title, description, _ = _build_copy(
        stage, payload.expires_at, grace_days, is_trial=payload.ends_with_trial
    )

    batch_create_notifications(
        user_ids=[user.id],
        notif_type=NotificationType.LICENSE_EXPIRY_WARNING,
        db_session=db_session,
        title=title,
        description=description,
        additional_data=additional_data,
    )
