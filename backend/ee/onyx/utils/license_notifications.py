"""License-expiry tiered notification orchestration.

Drives email + in-app notification side effects. Idempotency is enforced
through the existing `notification` unique index
`(user_id, notif_type, COALESCE(additional_data, '{}'::jsonb))`. Pre-existing
admins for a given (stage, expires_at[, sent_date]) tuple are skipped — only
freshly-notified admins receive an email.
"""

from datetime import date
from datetime import datetime
from datetime import timezone
from typing import Any

from sqlalchemy import cast
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from ee.onyx.utils.license_expiry import ExpiryWarningStage
from ee.onyx.utils.license_expiry import get_grace_days_remaining
from onyx.auth.email_utils import build_html_email
from onyx.auth.email_utils import send_email
from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import EMAIL_CONFIGURED
from onyx.configs.constants import NotificationType
from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME
from onyx.db.models import Notification
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_admin_users(db_session: Session) -> list[User]:
    return list(
        db_session.execute(
            select(User).where(
                User.is_active,  # ty: ignore[invalid-argument-type]
                User.role == UserRole.ADMIN,
            )
        )
        .unique()
        .scalars()
        .all()
    )


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


def _send_email_for_stage(
    user_email: str, subject: str, heading: str, message: str
) -> None:
    if not EMAIL_CONFIGURED:
        logger.warning(
            "Email not configured — skipping license expiry email to %s", user_email
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


def _create_stage_notifications(
    *,
    db_session: Session,
    admin_ids: list,
    title: str,
    description: str,
    additional_data: dict[str, Any],
) -> set:
    if not admin_ids:
        return set()

    now = datetime.now(timezone.utc)
    normalized_data = additional_data if additional_data is not None else {}

    stmt = (
        insert(Notification)
        .values(
            [
                {
                    "user_id": admin_id,
                    "notif_type": NotificationType.LICENSE_EXPIRY_WARNING.name,
                    "title": title,
                    "description": description,
                    "dismissed": False,
                    "last_shown": now,
                    "first_shown": now,
                    "additional_data": normalized_data,
                }
                for admin_id in admin_ids
            ]
        )
        .on_conflict_do_nothing()
        .returning(Notification.user_id)
    )
    result = db_session.execute(stmt)
    inserted_ids = set(result.scalars())
    db_session.commit()
    return inserted_ids


def notify_admins_for_stage(
    db_session: Session,
    stage: ExpiryWarningStage,
    expires_at: datetime,
    today: date | None = None,
) -> int:
    """Create in-app notifications + send emails for admins not already notified.

    Returns count of admins newly notified.
    """
    if stage == ExpiryWarningStage.NONE:
        return 0

    if today is None:
        today = datetime.now(timezone.utc).date()

    admins = _get_admin_users(db_session)
    if not admins:
        logger.warning("No active admins found to notify for license stage %s", stage)
        return 0

    additional_data = _build_additional_data(stage, expires_at, today)

    already_notified_ids = set(
        db_session.execute(
            select(Notification.user_id).where(
                Notification.notif_type == NotificationType.LICENSE_EXPIRY_WARNING,
                func.coalesce(Notification.additional_data, cast({}, postgresql.JSONB))
                == additional_data,
            )
        ).scalars()
    )

    new_admins = [a for a in admins if a.id not in already_notified_ids]
    if not new_admins:
        return 0

    grace_days = get_grace_days_remaining(expires_at)
    title, description, email_subject = _build_copy(stage, expires_at, grace_days)

    admin_ids = [a.id for a in new_admins]
    inserted_admin_ids = _create_stage_notifications(
        db_session=db_session,
        admin_ids=admin_ids,
        title=title,
        description=description,
        additional_data=additional_data,
    )
    if not inserted_admin_ids:
        return 0

    admin_by_id = {admin.id: admin for admin in new_admins}

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
    return len(inserted_admin_ids)
