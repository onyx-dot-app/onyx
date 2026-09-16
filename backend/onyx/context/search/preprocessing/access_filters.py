from sqlalchemy.orm import Session

from onyx.access.access import get_acl_for_user
from onyx.db.models import User


def build_access_filters_for_user(user: User, session: Session) -> list[str]:
    user_acl = get_acl_for_user(user, session)
    return list(user_acl)
