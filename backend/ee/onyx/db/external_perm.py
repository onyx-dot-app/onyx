from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.db.models import PublicExternalUserGroup
from onyx.db.models import User
from onyx.db.models import User__ExternalUserGroupId
from onyx.db.users import batch_add_ext_perm_user_if_not_exists
from onyx.db.users import get_user_by_email
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ExternalUserGroup(BaseModel):
    id: str
    user_emails: list[str]
    # `True` for cases like a Folder in Google Drive that give domain-wide
    # or "Anyone with link" access to all files in the folder.
    # if this is set, `user_emails` don't really matter.
    # When this is `True`, this `ExternalUserGroup` object doesn't really represent
    # an actual "group" in the source.
    gives_anyone_access: bool = False


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


def delete_public_external_group_for_cc_pair__no_commit(
    db_session: Session,
    cc_pair_id: int,
) -> None:
    db_session.execute(
        delete(PublicExternalUserGroup).where(
            PublicExternalUserGroup.cc_pair_id == cc_pair_id
        )
    )


def mark_old_external_groups_as_stale(
    db_session: Session,
    cc_pair_id: int,
) -> None:
    db_session.execute(
        update(User__ExternalUserGroupId)
        .where(User__ExternalUserGroupId.cc_pair_id == cc_pair_id)
        .values(stale=True)
    )
    db_session.execute(
        update(PublicExternalUserGroup)
        .where(PublicExternalUserGroup.cc_pair_id == cc_pair_id)
        .values(stale=True)
    )


def upsert_external_groups(
    db_session: Session,
    cc_pair_id: int,
    external_groups: list[ExternalUserGroup],
    source: DocumentSource,
) -> None:
    """
    Performs a true upsert operation for external user groups:
    - For existing groups (same user_id, external_user_group_id, cc_pair_id), updates the stale flag to False
    - For new groups, inserts them with stale=False
    - For public groups, uses upsert logic as well
    """
    # If there are no groups to add, return early
    if not external_groups:
        return

    # collect all emails from all groups to batch add all users at once for efficiency
    all_group_member_emails = set()
    for external_group in external_groups:
        for user_email in external_group.user_emails:
            all_group_member_emails.add(user_email)

    # batch add users if they don't exist and get their ids
    all_group_members: list[User] = batch_add_ext_perm_user_if_not_exists(
        db_session=db_session,
        # NOTE: this function handles case sensitivity for emails
        emails=list(all_group_member_emails),
    )

    # map emails to ids
    email_id_map = {user.email.lower(): user.id for user in all_group_members}

    # Process each external group
    for external_group in external_groups:
        external_group_id = build_ext_group_name_for_onyx(
            ext_group_name=external_group.id,
            source=source,
        )

        # Handle user-group mappings
        for user_email in external_group.user_emails:
            user_id = email_id_map.get(user_email.lower())
            if user_id is None:
                logger.warning(
                    f"User in group {external_group.id}"
                    f" with email {user_email} not found"
                )
                continue

            # Check if the user-group mapping already exists
            existing_user_group = db_session.scalar(
                select(User__ExternalUserGroupId).where(
                    User__ExternalUserGroupId.user_id == user_id,
                    User__ExternalUserGroupId.external_user_group_id
                    == external_group_id,
                    User__ExternalUserGroupId.cc_pair_id == cc_pair_id,
                )
            )

            if existing_user_group:
                # Update existing record
                existing_user_group.stale = False
            else:
                # Insert new record
                new_user_group = User__ExternalUserGroupId(
                    user_id=user_id,
                    external_user_group_id=external_group_id,
                    cc_pair_id=cc_pair_id,
                    stale=False,
                )
                db_session.add(new_user_group)

        # Handle public group if needed
        if external_group.gives_anyone_access:
            # Check if the public group already exists
            existing_public_group = db_session.scalar(
                select(PublicExternalUserGroup).where(
                    PublicExternalUserGroup.external_user_group_id == external_group_id,
                    PublicExternalUserGroup.cc_pair_id == cc_pair_id,
                )
            )

            if existing_public_group:
                # Update existing record
                existing_public_group.stale = False
            else:
                # Insert new record
                new_public_group = PublicExternalUserGroup(
                    external_user_group_id=external_group_id,
                    cc_pair_id=cc_pair_id,
                    stale=False,
                )
                db_session.add(new_public_group)

    db_session.commit()


def remove_stale_external_groups(
    db_session: Session,
    cc_pair_id: int,
) -> None:
    db_session.execute(
        delete(User__ExternalUserGroupId).where(
            User__ExternalUserGroupId.cc_pair_id == cc_pair_id,
            User__ExternalUserGroupId.stale.is_(True),
        )
    )
    db_session.execute(
        delete(PublicExternalUserGroup).where(
            PublicExternalUserGroup.cc_pair_id == cc_pair_id,
            PublicExternalUserGroup.stale.is_(True),
        )
    )
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


def fetch_external_groups_for_user_email_and_group_ids(
    db_session: Session,
    user_email: str,
    group_ids: list[str],
) -> list[User__ExternalUserGroupId]:
    user = get_user_by_email(db_session=db_session, email=user_email)
    if user is None:
        return []
    user_id = user.id
    user_ext_groups = db_session.scalars(
        select(User__ExternalUserGroupId).where(
            User__ExternalUserGroupId.user_id == user_id,
            User__ExternalUserGroupId.external_user_group_id.in_(group_ids),
        )
    ).all()
    return list(user_ext_groups)


def fetch_public_external_group_ids(
    db_session: Session,
) -> list[str]:
    return list(
        db_session.scalars(select(PublicExternalUserGroup.external_user_group_id)).all()
    )
