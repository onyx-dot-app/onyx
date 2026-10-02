from sqlalchemy.orm import Session

from onyx.access.access import get_acl_for_user
from onyx.access.cc_pair_access import get_cc_pair_access_mode
from onyx.access.utils import EXTERNAL_GROUP_ACL_PREFIX, USER_EMAIL_ACL_PREFIX
from onyx.context.search.models import CCPairAccessFilter, UserAccessFilters
from onyx.db.connector_credential_pair import get_cc_pair_access_sets_for_user
from onyx.db.models import User


def build_access_filters_for_user(user: User, session: Session) -> UserAccessFilters:
    user_acl = get_acl_for_user(user, session)
    return UserAccessFilters(
        access_control_list=list(user_acl),
        cc_pair_access=_build_cc_pair_access_filter(user, user_acl, session),
    )


def _build_cc_pair_access_filter(
    user: User, user_acl: set[str], db_session: Session
) -> CCPairAccessFilter | None:
    mode = get_cc_pair_access_mode(db_session)
    if mode is None:
        return None
    access_sets = get_cc_pair_access_sets_for_user(db_session, user)
    return CCPairAccessFilter(
        mode=mode,
        open_cc_pair_ids=sorted(access_sets.open_cc_pair_ids),
        acl_cc_pair_ids=sorted(access_sets.acl_cc_pair_ids),
        user_acl=sorted(
            entry
            for entry in user_acl
            if entry.startswith((USER_EMAIL_ACL_PREFIX, EXTERNAL_GROUP_ACL_PREFIX))
        ),
    )
