from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    # Commit immediately so the transaction closes before potentially long
    # external API calls (e.g. Google Drive folder iteration). Without this,
    # the DB connection sits idle-in-transaction during API calls and gets
    # killed by idle_in_transaction_session_timeout, causing the entire sync
    # to fail and stale cleanup to never run.
    db_session.commit()


_UPSERT_BATCH_SIZE = 5000


def upsert_external_groups(
    db_session: Session,
    cc_pair_id: int,
    external_groups: list[ExternalUserGroup],
    source: DocumentSource,
) -> None:
    """
    Batch upsert external user groups using INSERT ... ON CONFLICT DO UPDATE.
    - For existing rows (same user_id, external_user_group_id, cc_pair_id),
      sets stale=False
    - For new rows, inserts with stale=False
    - Same logic for PublicExternalUserGroup
    """
    if not external_groups:
        return

    # Collect all emails from all groups to batch-add users at once
    all_group_member_emails: set[str] = set()
    for external_group in external_groups:
        all_group_member_emails.update(external_group.user_emails)

    # Batch add users if they don't exist and get their ids
    all_group_members: list[User] = batch_add_ext_perm_user_if_not_exists(
        db_session=db_session,
        emails=list(all_group_member_emails),
    )

    email_id_map = {user.email.lower(): user.id for user in all_group_members}

    # Build all user-group mappings and public-group mappings
    user_group_mappings: list[dict] = []
    public_group_mappings: list[dict] = []

    for external_group in external_groups:
        external_group_id = build_ext_group_name_for_onyx(
            ext_group_name=external_group.id,
            source=source,
        )

        for user_email in external_group.user_emails:
            user_id = email_id_map.get(user_email.lower())
            if user_id is None:
                logger.warning(
                    "User in group %s with email %s not found",
                    external_group.id,
                    user_email,
                )
                continue

            user_group_mappings.append(
                {
                    "user_id": user_id,
                    "external_user_group_id": external_group_id,
                    "cc_pair_id": cc_pair_id,
                    "stale": False,
                }
            )

        if external_group.gives_anyone_access:
            public_group_mappings.append(
                {
                    "external_user_group_id": external_group_id,
                    "cc_pair_id": cc_pair_id,
                    "stale": False,
                }
            )

    # Deduplicate to avoid "ON CONFLICT DO UPDATE command cannot affect row
    # a second time" when duplicate emails or overlapping groups produce
    # identical (user_id, external_user_group_id, cc_pair_id) tuples.
    user_group_mappings_deduped = list(
        {
            (m["user_id"], m["external_user_group_id"], m["cc_pair_id"]): m
            for m in user_group_mappings
        }.values()
    )

    # Batch upsert user-group mappings
    for i in range(0, len(user_group_mappings_deduped), _UPSERT_BATCH_SIZE):
        chunk = user_group_mappings_deduped[i : i + _UPSERT_BATCH_SIZE]
        stmt = pg_insert(User__ExternalUserGroupId).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "external_user_group_id", "cc_pair_id"],
            set_={"stale": False},
        )
        db_session.execute(stmt)

    # Deduplicate public group mappings as well
    public_group_mappings_deduped = list(
        {
            (m["external_user_group_id"], m["cc_pair_id"]): m
            for m in public_group_mappings
        }.values()
    )

    # Batch upsert public group mappings
    for i in range(0, len(public_group_mappings_deduped), _UPSERT_BATCH_SIZE):
        chunk = public_group_mappings_deduped[i : i + _UPSERT_BATCH_SIZE]
        stmt = pg_insert(PublicExternalUserGroup).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["external_user_group_id", "cc_pair_id"],
            set_={"stale": False},
        )
        db_session.execute(stmt)

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
