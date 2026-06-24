from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from onyx.configs.constants import DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN
from onyx.configs.constants import NotificationType
from onyx.db.enums import AccountType
from onyx.db.models import Notification
from onyx.db.models import User
from onyx.db.notification import batch_create_notifications
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _eligible_user_ids_query() -> Select[tuple[UUID]]:
    return select(User.id).where(  # ty: ignore[no-matching-overload]
        User.is_active.is_(True),  # ty: ignore[unresolved-attribute]
        User.account_type.notin_([AccountType.BOT, AccountType.EXT_PERM_USER]),
        ~User.email.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN),
    )


def get_active_admin_banner(db_session: Session) -> Notification | None:
    # No `dismissed` filter on purpose: a banner stays published until an admin
    # clears it, regardless of per-user dismissals — and late-joiner minting in
    # `ensure_admin_banner_for_user` relies on reading it while published.
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
    # Resolve recipients first: with zero eligible users there is nobody to
    # publish to, so return None and leave any existing banner untouched — the
    # delete+insert swap below only runs once we know there are recipients.
    user_ids = list(db_session.scalars(_eligible_user_ids_query()).all())
    if not user_ids:
        logger.warning("Admin banner not set: tenant has no eligible users")
        return None

    # Delete + insert in one transaction we commit ourselves, so the swap is
    # atomic and owns its commit boundary instead of depending on the helper.
    # Constant additional_data lets the unique index on
    # (user_id, notif_type, COALESCE(additional_data, '{}')) serialize concurrent PUTs.
    db_session.query(Notification).filter(
        Notification.notif_type == NotificationType.ADMIN_BANNER
    ).delete(synchronize_session=False)

    batch_create_notifications(
        user_ids,
        NotificationType.ADMIN_BANNER,
        db_session,
        title=title,
        description=content,
        additional_data={},
        commit=False,
    )
    db_session.commit()
    logger.info(
        "Admin banner set for %s eligible users (title=%s chars, content=%s chars)",
        len(user_ids),
        len(title),
        len(content) if content else 0,
    )
    return get_active_admin_banner(db_session)


def ensure_admin_banner_for_user(db_session: Session, user: User) -> None:
    if not user.is_active:
        return
    if user.account_type in (AccountType.BOT, AccountType.EXT_PERM_USER):
        return
    if user.email.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN):
        return

    banner = get_active_admin_banner(db_session)
    if banner is None:
        return

    existing_id = db_session.scalar(
        select(Notification.id)
        .where(
            Notification.user_id == user.id,
            Notification.notif_type == NotificationType.ADMIN_BANNER,
        )
        .limit(1)
    )
    if existing_id is not None:
        return

    batch_create_notifications(
        [user.id],
        NotificationType.ADMIN_BANNER,
        db_session,
        title=banner.title,
        description=banner.description,
        additional_data={},
    )
