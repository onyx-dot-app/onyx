from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.access.utils import prefix_group_w_source
from danswer.configs.constants import DocumentSource
from danswer.db.models import User__ExternalUserGroupId
from danswer.db.users import batch_add_ext_perm_user_if_not_exists


class ExternalUserGroup(BaseModel):
    id: str
    user_emails: list[str]


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


def replace_user__ext_group_for_cc_pair(
    db_session: Session,
    cc_pair_id: int,
    group_defs: list[ExternalUserGroup],
    source: DocumentSource,
) -> None:
    """
    This function clears all existing external user group relations for a given cc_pair_id
    and replaces them with the new group definitions and commits the changes.
    """

    # collect all emails from all groups to batch add all users at once for efficiency
    all_group_member_emails = set()
    for external_group in group_defs:
        for user_email in external_group.user_emails:
            all_group_member_emails.add(user_email)

    # batch add users if they don't exist and get their ids
    all_group_members = batch_add_ext_perm_user_if_not_exists(
        db_session=db_session, emails=list(all_group_member_emails)
    )

    delete_user__ext_group_for_cc_pair__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )

    # map emails to ids
    email_id_map = {user.email: user.id for user in all_group_members}

    # use these ids to create new external user group relations relating group_id to user_ids
    new_external_permissions = []
    for external_group in group_defs:
        for user_email in external_group.user_emails:
            user_id = email_id_map[user_email]
            new_external_permissions.append(
                User__ExternalUserGroupId(
                    user_id=user_id,
                    external_user_group_id=prefix_group_w_source(
                        external_group.id, source
                    ),
                    cc_pair_id=cc_pair_id,
                )
            )

    db_session.add_all(new_external_permissions)
    db_session.commit()


def fetch_external_groups_for_user(
    db_session: Session,
    user_id: UUID,
) -> Sequence[User__ExternalUserGroupId]:
    return db_session.scalars(
        select(User__ExternalUserGroupId).where(
            User__ExternalUserGroupId.user_id == user_id
        )
    ).all()
