from sqlalchemy.orm import Session

from onyx.db.index_attempt import delete_index_attempts
from onyx.db.permission_sync_attempt import (
    delete_doc_permission_sync_attempts__no_commit,
)
from onyx.db.permission_sync_attempt import (
    delete_external_group_permission_sync_attempts__no_commit,
)
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop


def delete_cc_pair_dependencies__no_commit(
    db_session: Session,
    cc_pair_id: int,
) -> None:
    fetch_ee_implementation_or_noop(
        "onyx.db.external_perm",
        "delete_user__ext_group_for_cc_pair__no_commit",
    )(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )

    delete_index_attempts(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    delete_doc_permission_sync_attempts__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    delete_external_group_permission_sync_attempts__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
