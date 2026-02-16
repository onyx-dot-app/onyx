from sqlalchemy.orm import Session

from ee.onyx.db.external_perm import fetch_external_groups_for_user
from onyx.db.models import User


def _get_user_external_group_ids(db_session: Session, user: User) -> list[str]:
    if not user:
        return []
    external_groups = fetch_external_groups_for_user(db_session, user.id)
    return [external_group.external_user_group_id for external_group in external_groups]
