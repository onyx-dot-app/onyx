from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
from onyx.db.admin_banner import get_admin_banner
from onyx.db.models import User
from onyx.db.notification import create_notification


def ensure_permissions_migration_notification(user: User, db_session: Session) -> None:
    # Feature id "permissions_migration_v1" must not change after shipping —
    # it is the dedup key on (user_id, notif_type, additional_data).
    create_notification(
        user_id=user.id,
        notif_type=NotificationType.FEATURE_ANNOUNCEMENT,
        db_session=db_session,
        title="Permissions are changing in Onyx",
        description="Roles are moving to group-based permissions. Click for details.",
        additional_data={
            "feature": "permissions_migration_v1",
            "link": "https://docs.onyx.app/admins/permissions/whats_changing",
        },
        refresh_existing=False,
    )


def ensure_system_announcement_notification(user: User, db_session: Session) -> None:
    """Materialize the admin-authored site-wide announcement as a per-user
    notification so it flows through the bell + banner queue with the normal
    per-user dismissal. Re-show on edit is driven by the admin API clearing the
    rows, so a repeat read within one banner just returns the existing row."""
    banner = get_admin_banner()
    if banner is None:
        return
    create_notification(
        user_id=user.id,
        notif_type=NotificationType.SYSTEM_ANNOUNCEMENT,
        db_session=db_session,
        title=banner.title,
        description=banner.content,
        # Empty dict, not None: create_notification stores None as JSONB null,
        # which the COALESCE(additional_data, '{}') dedup won't match, so every
        # read would re-insert and hit the unique index.
        additional_data={},
        refresh_existing=False,
    )
