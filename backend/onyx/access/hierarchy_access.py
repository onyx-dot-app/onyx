from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.utils.variable_functionality import fetch_versioned_implementation


def _get_user_external_group_ids(db_session: Session, user: User) -> list[str]:
    return []


def get_user_external_group_ids(db_session: Session, user: User) -> list[str]:
    versioned_get_user_external_group_ids = fetch_versioned_implementation(
        "onyx.access.hierarchy_access", "_get_user_external_group_ids"
    )
    return versioned_get_user_external_group_ids(db_session, user)
