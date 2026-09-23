"""Data-access groups of SYNC_RESTRICTED cc-pairs (see UserGroup__CCPairDataAccess)."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.models import UserGroup, UserGroup__CCPairDataAccess


def fetch_existing_user_group_ids(
    db_session: Session, user_group_ids: list[int]
) -> set[int]:
    if not user_group_ids:
        return set()
    return set(
        db_session.scalars(
            select(UserGroup.id).where(UserGroup.id.in_(user_group_ids))
        ).all()
    )


def fetch_data_access_group_ids(db_session: Session, cc_pair_id: int) -> list[int]:
    return list(
        db_session.scalars(
            select(UserGroup__CCPairDataAccess.user_group_id)
            .where(UserGroup__CCPairDataAccess.cc_pair_id == cc_pair_id)
            .order_by(UserGroup__CCPairDataAccess.user_group_id)
        ).all()
    )


def replace_data_access_groups(
    db_session: Session, cc_pair_id: int, user_group_ids: list[int]
) -> None:
    """Set the pair's data-access groups to exactly ``user_group_ids``."""
    db_session.execute(
        delete(UserGroup__CCPairDataAccess).where(
            UserGroup__CCPairDataAccess.cc_pair_id == cc_pair_id
        )
    )
    db_session.add_all(
        UserGroup__CCPairDataAccess(cc_pair_id=cc_pair_id, user_group_id=group_id)
        for group_id in sorted(set(user_group_ids))
    )
    db_session.commit()
