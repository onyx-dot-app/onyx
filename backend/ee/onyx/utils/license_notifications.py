"""License-expiry tiered notification orchestration.

Drives email + in-app notification side effects. Idempotency is enforced
through the existing `notification` unique index
`(user_id, notif_type, COALESCE(additional_data, '{}'::jsonb))`. Pre-existing
admins for a given (stage, expires_at[, sent_date]) tuple are skipped — only
freshly-notified admins receive an email.

Email delivery has two paths:
- Local SMTP/SendGrid when ``EMAIL_CONFIGURED`` — one message per admin.
- Cloud control-plane fallback otherwise — one message to the license
  registrant (Stripe customer email), routed via the cloud data plane
  proxy. Air-gapped instances log a warning and rely on the in-app banner.
"""

from datetime import date
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import CLOUD_DATA_PLANE_URL
from ee.onyx.db.license import get_license
from ee.onyx.utils.license_expiry import ExpiryWarningStage
from ee.onyx.utils.license_expiry import get_grace_days_remaining
from onyx.auth.email_utils import build_html_email
from onyx.auth.email_utils import send_email
from onyx.configs.app_configs import EMAIL_CONFIGURED
from onyx.configs.constants import NotificationType
from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME
from onyx.db.notification import batch_create_notifications
from onyx.db.users import get_active_admin_users
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _build_copy(
    stage: ExpiryWarningStage,
    expires_at: datetime,
    grace_days_remaining: int,
) -> tuple[str, str, str]:
    """Returns (banner_title, banner_description, email_subject)."""
    expires_str = expires_at.strftime("%Y-%m-%d")
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
            f"Onyx license expired — {grace_days_remaining} grace days remaining",
            f"Your license expired on {expires_str}. You have "
            f"{grace_days_remaining} day(s) of grace access remaining before "
            "the instance is gated. Renew now.",
            f"Onyx license expired — {grace_days_remaining} grace days remaining",
        )
    raise ValueError(f"Unsupported stage for notification copy: {stage}")


def _send_local_email(
    user_email: str, subject: str, heading: str, message: str
) -> None:
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


def _send_via_control_plane(
    db_session: Session,
    stage: ExpiryWarningStage,
    expires_at: datetime,
    grace_days_remaining: int,
) -> bool:
    """Forward a license-expiry email request through the cloud DP proxy.

    The proxy authenticates with our license blob and the control plane
    resolves the Stripe customer email as the recipient. Returns True if
    the proxy reports the message was accepted.
    """
    license_row = get_license(db_session)
    if not license_row or not license_row.license_data:
        logger.warning(
            "No local license available — cannot fall back to control-plane email"
        )
        return False

    url = f"{CLOUD_DATA_PLANE_URL}/proxy/send-license-expiry-email"
    body: dict[str, Any] = {
        "stage": stage.value,
        "expires_at": expires_at.isoformat(),
    }
    if stage == ExpiryWarningStage.GRACE:
        body["grace_days_remaining"] = grace_days_remaining

    try:
        response = requests.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {license_row.license_data}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        response.raise_for_status()
        sent = bool(response.json().get("sent", False))
        if not sent:
            logger.warning(
                "Control-plane license-expiry email reported not sent: %s",
                response.json().get("detail"),
            )
        return sent
    except requests.RequestException:
        logger.exception(
            "Failed to deliver license-expiry email via control plane (stage=%s)",
            stage.value,
        )
        return False


def _build_additional_data(
    stage: ExpiryWarningStage,
    expires_at: datetime,
    today: date,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "stage": stage.value,
        "expires_at": expires_at.isoformat(),
    }
    if stage == ExpiryWarningStage.GRACE:
        # Grace period sends one notification per UTC date so admins are
        # reminded daily until they renew.
        data["sent_date"] = today.isoformat()
    return data


def notify_admins_for_stage(
    db_session: Session,
    stage: ExpiryWarningStage,
    expires_at: datetime,
) -> None:
    """Create in-app notifications + send emails for admins not already notified."""
    if stage == ExpiryWarningStage.NONE:
        return

    today = datetime.now(timezone.utc).date()
    admins = get_active_admin_users(db_session)
    if not admins:
        logger.warning("No active admins found to notify for license stage %s", stage)
        return

    additional_data = _build_additional_data(stage, expires_at, today)
    grace_days = get_grace_days_remaining(expires_at)
    title, description, email_subject = _build_copy(stage, expires_at, grace_days)

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

    if EMAIL_CONFIGURED:
        admin_by_id = {admin.id: admin for admin in admins}
        for admin_id in inserted_admin_ids:
            admin = admin_by_id.get(admin_id)
            if admin is not None and admin.email:
                _send_local_email(
                    user_email=admin.email,
                    subject=email_subject,
                    heading=title,
                    message=description,
                )
    else:
        # Fall back to the control plane: it resolves the Stripe customer
        # email and delivers via SendGrid. One message per fire (not per
        # admin) because the registrant is per-tenant. Air-gapped
        # deployments will hit the request error path and rely on the
        # in-app banner instead.
        _send_via_control_plane(
            db_session=db_session,
            stage=stage,
            expires_at=expires_at,
            grace_days_remaining=grace_days,
        )

    logger.info(
        "License expiry notifications sent: stage=%s admins=%d date=%s",
        stage.value,
        len(inserted_admin_ids),
        today.isoformat(),
    )
