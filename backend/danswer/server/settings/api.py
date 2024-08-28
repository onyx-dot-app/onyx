from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.auth.users import current_user
from danswer.auth.users import is_user_admin
from danswer.configs.constants import KV_REINDEX_KEY
from danswer.configs.constants import NotificationType
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.db.notification import create_notification
from danswer.db.notification import dismiss_all_notifications
from danswer.db.notification import dismiss_notification
from danswer.db.notification import get_notification_by_id
from danswer.db.notification import get_notifications
from danswer.db.notification import update_notification_last_shown
from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.dynamic_configs.interface import ConfigNotFoundError
from danswer.server.settings.models import Notification
from danswer.server.settings.models import Settings
from danswer.server.settings.models import UserSettings
from danswer.server.settings.store import load_settings
from danswer.server.settings.store import store_settings
from danswer.utils.logger import setup_logger


logger = setup_logger()


admin_router = APIRouter(prefix="/admin/settings")
basic_router = APIRouter(prefix="/settings")


@admin_router.put("")
def put_settings(
    settings: Settings, _: User | None = Depends(current_admin_user)
) -> None:
    try:
        settings.check_validity()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store_settings(settings)


@basic_router.get("")
def fetch_settings(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserSettings:
    """Settings and notifications are stuffed into this single endpoint to reduce number of
    Postgres calls"""
    general_settings = load_settings()
    user_notifications = get_user_notifications(user, db_session)

    try:
        kv_store = get_dynamic_config_store()
        needs_reindexing = cast(bool, kv_store.load(KV_REINDEX_KEY))
    except ConfigNotFoundError:
        needs_reindexing = False

    return UserSettings(
        **general_settings.dict(),
        notifications=user_notifications,
        needs_reindexing=needs_reindexing
    )


@basic_router.post("/notifications/{notification_id}/dismiss")
def dismiss_notification_endpoint(
    notification_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        notification = get_notification_by_id(notification_id, user, db_session)
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="Not authorized to dismiss this notification"
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Notification not found")

    dismiss_notification(notification, db_session)


def get_user_notifications(
    user: User | None, db_session: Session
) -> list[Notification]:
    """Get notifications for the user, currently the logic is very specific to the reindexing flag"""
    is_admin = is_user_admin(user)
    if not is_admin:
        # Reindexing flag should only be shown to admins, basic users can't trigger it anyway
        return []

    kv_store = get_dynamic_config_store()
    try:
        needs_index = cast(bool, kv_store.load(KV_REINDEX_KEY))
        if not needs_index:
            dismiss_all_notifications(
                notif_type=NotificationType.REINDEX, db_session=db_session
            )
            return []
    except ConfigNotFoundError:
        # If something goes wrong and the flag is gone, better to not start a reindexing
        # it's a heavyweight long running job and maybe this flag is cleaned up later
        logger.warning("Could not find reindex flag")
        return []

    try:
        # Need a transaction in order to prevent under-counting current notifications
        db_session.begin()

        reindex_notifs = get_notifications(
            user=user, notif_type=NotificationType.REINDEX, db_session=db_session
        )

        if not reindex_notifs:
            notif = create_notification(
                user=user,
                notif_type=NotificationType.REINDEX,
                db_session=db_session,
            )
            db_session.flush()
            db_session.commit()
            return [Notification.from_model(notif)]

        if len(reindex_notifs) > 1:
            logger.error("User has multiple reindex notifications")

        reindex_notif = reindex_notifs[0]
        update_notification_last_shown(
            notification=reindex_notif, db_session=db_session
        )

        db_session.commit()
        return [Notification.from_model(reindex_notif)]
    except SQLAlchemyError:
        logger.exception("Error while processing notifications")
        db_session.rollback()
        return []
