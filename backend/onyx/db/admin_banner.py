from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from onyx.configs.constants import NotificationType
from onyx.db.enums import AccountType
from onyx.db.models import Notification
from onyx.db.models import User
from onyx.db.notification import batch_create_notifications
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _eligible_user_ids_query():  # type: ignore[no-untyped-def]
    return select(User.id).where(  # ty: ignore[no-matching-overload]
        User.is_active == True,  # noqa: E712
        User.account_type.notin_([AccountType.BOT, AccountType.EXT_PERM_USER]),
        User.email.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN).is_(  # ty: ignore[unresolved-attribute]
            False
        ),
    )


def get_active_admin_banner(db_session: Session) -> Notification | None:
    stmt = (
        select(Notification)
        .where(Notification.notif_type == NotificationType.ADMIN_BANNER)
        .order_by(Notification.first_shown.desc())
        .limit(1)
    )
    return db_session.scalars(stmt).first()


def clear_admin_banner(db_session: Session) -> None:
    db_session.query(Notification).filter(
        Notification.notif_type == NotificationType.ADMIN_BANNER
    ).delete(synchronize_session=False)
    db_session.commit()


def set_admin_banner(
    db_session: Session,
    title: str,
    content: str | None,
) -> Notification | None:
    # DELETE here is uncommitted; batch_create_notifications commits once,
    # making the swap atomic. Constant additional_data lets the unique index
    # on (user_id, notif_type, COALESCE(additional_data, '{}'))
    # serialize concurrent PUTs.
    db_session.query(Notification).filter(
        Notification.notif_type == NotificationType.ADMIN_BANNER
    ).delete(synchronize_session=False)

    user_ids = list(db_session.scalars(_eligible_user_ids_query()).all())
    batch_create_notifications(
        user_ids,
        NotificationType.ADMIN_BANNER,
        db_session,
        title=title,
        description=content,
        additional_data={},
    )
    logger.info(
        "Admin banner set for %s eligible users (title=%s chars, content=%s chars)",
        len(user_ids),
        len(title),
        len(content) if content else 0,
    )
    return get_active_admin_banner(db_session)
