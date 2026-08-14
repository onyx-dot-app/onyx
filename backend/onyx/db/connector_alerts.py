from typing import Any

from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.enums import NotificationSeverity
from onyx.db.notification import (
    batch_create_notifications,
    delete_notifications_by_additional_data,
)
from onyx.db.users import get_active_admin_users
from onyx.utils.logger import setup_logger

logger = setup_logger()


def connector_alert_additional_data(cc_pair_id: int) -> dict[str, Any]:
    """Dedup key for connector alerts; cleanup deletes by exact match on it."""
    return {
        "cc_pair_id": cc_pair_id,
        "link": f"/admin/connector/{cc_pair_id}",
    }


def notify_admins_of_connector_alert(
    db_session: Session,
    cc_pair_id: int,
    notif_type: NotificationType,
    title: str,
    description: str,
) -> None:
    """Best-effort ERROR alert to all active admins; never raises.

    Commits the inserts on success; rolls the session back on failure. Call
    it with no uncommitted work pending on the session."""
    try:
        batch_create_notifications(
            user_ids=[admin.id for admin in get_active_admin_users(db_session)],
            notif_type=notif_type,
            db_session=db_session,
            title=title,
            description=description,
            additional_data=connector_alert_additional_data(cc_pair_id),
            severity=NotificationSeverity.ERROR,
        )
    except Exception:
        # Leave the caller's session usable: a failed insert would otherwise
        # poison the transaction and break the connector update that follows.
        db_session.rollback()
        logger.exception(
            "Failed to send %s alert for cc_pair %s", notif_type.value, cc_pair_id
        )


def clear_connector_alerts__no_commit(
    db_session: Session,
    cc_pair_id: int,
    notif_type: NotificationType,
) -> None:
    """Delete every admin's alert for this connector so the next incident
    creates a fresh one. Caller commits."""
    delete_notifications_by_additional_data(
        notif_type=notif_type,
        db_session=db_session,
        additional_data=connector_alert_additional_data(cc_pair_id),
    )
