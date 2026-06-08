from sqlalchemy.orm import Session

from onyx.configs.constants import NotificationType
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
    )
