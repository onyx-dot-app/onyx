from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.access.utils import prefix_group_w_source
from danswer.configs.constants import DocumentSource
from danswer.db.models import User__ExternalUserGroupId


class ExternalUserGroup(BaseModel):
    id: str
    user_ids: list[UUID]


def delete_user__ext_group_for_user__no_commit(
    db_session: Session,
    user_id: UUID,
) -> None:
    db_session.execute(
        delete(User__ExternalUserGroupId).where(
            User__ExternalUserGroupId.user_id == user_id
        )
    )


def delete_user__ext_group_for_cc_pair__no_commit(
    db_session: Session,
    cc_pair_id: int,
) -> None:
    db_session.execute(
        delete(User__ExternalUserGroupId).where(
            User__ExternalUserGroupId.cc_pair_id == cc_pair_id
        )
    )


def replace_user__ext_group_for_cc_pair__no_commit(
    db_session: Session,
    cc_pair_id: int,
    group_defs: list[ExternalUserGroup],
    source: DocumentSource,
) -> None:
    """
    This function clears all existing external user group relations for a given cc_pair_id
    and replaces them with the new group definitions.
    """
    delete_user__ext_group_for_cc_pair__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )

    new_external_permissions = [
        User__ExternalUserGroupId(
            user_id=user_id,
            external_user_group_id=prefix_group_w_source(external_group.id, source),
            cc_pair_id=cc_pair_id,
        )
        for external_group in group_defs
        for user_id in external_group.user_ids
    ]

    db_session.add_all(new_external_permissions)


def fetch_external_groups_for_user(
    db_session: Session,
    user_id: UUID,
) -> Sequence[User__ExternalUserGroupId]:
    return db_session.scalars(
        select(User__ExternalUserGroupId).where(
            User__ExternalUserGroupId.user_id == user_id
        )
    ).all()
