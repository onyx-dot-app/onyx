from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.auth.users import is_user_admin
from onyx.configs.constants import KV_REINDEX_KEY
from onyx.configs.constants import NotificationType
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.notification import create_notification
from onyx.db.notification import dismiss_all_notifications
from onyx.db.notification import get_notifications
from onyx.db.notification import update_notification_last_shown
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.settings.models import Notification
from onyx.server.settings.models import Settings
from onyx.server.settings.models import UserSettings
from onyx.server.settings.store import load_settings
from onyx.server.settings.store import store_settings
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/settings")
basic_router = APIRouter(prefix="/settings")


@admin_router.put("")
def admin_put_settings(
    settings: Settings, _: User | None = Depends(current_admin_user)
) -> None:
    store_settings(settings)


@basic_router.get("")
def fetch_settings(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserSettings:
    """Settings and notifications are stuffed into this single endpoint to reduce number of
    Postgres calls"""
    general_settings = load_settings()
    settings_notifications = get_settings_notifications(user, db_session)

    try:
        kv_store = get_kv_store()
        needs_reindexing = cast(bool, kv_store.load(KV_REINDEX_KEY))
    except KvKeyNotFoundError:
        needs_reindexing = False

    return UserSettings(
        **general_settings.model_dump(),
        notifications=settings_notifications,
        needs_reindexing=needs_reindexing,
    )


def get_settings_notifications(
    user: User | None, db_session: Session
) -> list[Notification]:
    """Get notifications for settings page, including product gating and reindex notifications"""
    # Check for product gating notification
    product_notif = get_notifications(
        user=None,
        notif_type=NotificationType.TRIAL_ENDS_TWO_DAYS,
        db_session=db_session,
    )
    notifications = [Notification.from_model(product_notif[0])] if product_notif else []

    # Only show reindex notifications to admins
    is_admin = is_user_admin(user)
    if not is_admin:
        return notifications

    # Check if reindexing is needed
    kv_store = get_kv_store()
    try:
        needs_index = cast(bool, kv_store.load(KV_REINDEX_KEY))
        if not needs_index:
            dismiss_all_notifications(
                notif_type=NotificationType.REINDEX, db_session=db_session
            )
            return notifications
    except KvKeyNotFoundError:
        # If something goes wrong and the flag is gone, better to not start a reindexing
        # it's a heavyweight long running job and maybe this flag is cleaned up later
        logger.warning("Could not find reindex flag")
        return notifications

    try:
        # Need a transaction in order to prevent under-counting current notifications
        reindex_notifs = get_notifications(
            user=user, notif_type=NotificationType.REINDEX, db_session=db_session
        )

        if not reindex_notifs:
            notif = create_notification(
                user_id=user.id if user else None,
                notif_type=NotificationType.REINDEX,
                db_session=db_session,
            )
            db_session.flush()
            db_session.commit()

            notifications.append(Notification.from_model(notif))
            return notifications

        if len(reindex_notifs) > 1:
            logger.error("User has multiple reindex notifications")

        reindex_notif = reindex_notifs[0]
        update_notification_last_shown(
            notification=reindex_notif, db_session=db_session
        )

        db_session.commit()
        notifications.append(Notification.from_model(reindex_notif))
        return notifications
    except SQLAlchemyError:
        logger.exception("Error while processing notifications")
        db_session.rollback()
        return notifications
