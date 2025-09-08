from datetime import datetime
from enum import Enum
from typing import TypeVarTuple

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy import desc
from sqlalchemy import exists
from sqlalchemy import lateral
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import true
from sqlalchemy import update
from sqlalchemy.orm import aliased
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_AUTH
from onyx.configs.app_configs import USER_FILE_INDEXING_LIMIT
from onyx.configs.constants import DocumentSource
from onyx.db.connector import fetch_connector_by_id
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.credentials import fetch_credential_by_id_for_user
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexingStatus
from onyx.db.models import SearchSettings
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.db.models import UserRole
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

logger = setup_logger()

R = TypeVarTuple("R")


class ConnectorType(str, Enum):
    STANDARD = "standard"
    USER_FILE = "user_file"


def _add_user_filters(
    stmt: Select[tuple[*R]], user: User | None, get_editable: bool = True
) -> Select[tuple[*R]]:
    # If user is None and auth is disabled, assume the user is an admin
    if (user is None and DISABLE_AUTH) or (user and user.role == UserRole.ADMIN):
        return stmt

    stmt = stmt.distinct()
    UG__CCpair = aliased(UserGroup__ConnectorCredentialPair)
    User__UG = aliased(User__UserGroup)

    """
    Here we select cc_pairs by relation:
    User -> User__UserGroup -> UserGroup__ConnectorCredentialPair ->
    ConnectorCredentialPair
    """
    stmt = stmt.outerjoin(UG__CCpair).outerjoin(
        User__UG,
        User__UG.user_group_id == UG__CCpair.user_group_id,
    )

    """
    Filter cc_pairs by:
    - if the user is in the user_group that owns the cc_pair
    - if the user is not a global_curator, they must also have a curator relationship
    to the user_group
    - if editing is being done, we also filter out cc_pairs that are owned by groups
    that the user isn't a curator for
    - if we are not editing, we show all cc_pairs in the groups the user is a curator
    for (as well as public cc_pairs)
    """

    # If user is None, this is an anonymous user and we should only show public cc_pairs
    if user is None:
        where_clause = ConnectorCredentialPair.access_type == AccessType.PUBLIC
        return stmt.where(where_clause)

    where_clause = User__UG.user_id == user.id
    if user.role == UserRole.CURATOR and get_editable:
        where_clause &= User__UG.is_curator == True  # noqa: E712
    if get_editable:
        user_groups = select(User__UG.user_group_id).where(User__UG.user_id == user.id)
        if user.role == UserRole.CURATOR:
            user_groups = user_groups.where(
                User__UserGroup.is_curator == True  # noqa: E712
            )
        where_clause &= (
            ~exists()
            .where(UG__CCpair.cc_pair_id == ConnectorCredentialPair.id)
            .where(~UG__CCpair.user_group_id.in_(user_groups))
            .correlate(ConnectorCredentialPair)
        )
        where_clause |= ConnectorCredentialPair.creator_id == user.id
    else:
        where_clause |= ConnectorCredentialPair.access_type == AccessType.PUBLIC
        where_clause |= ConnectorCredentialPair.access_type == AccessType.SYNC

    return stmt.where(where_clause)


def get_connector_credential_pairs_for_user(
    db_session: Session,
    user: User | None,
    get_editable: bool = True,
    ids: list[int] | None = None,
    eager_load_connector: bool = False,
    eager_load_credential: bool = False,
    eager_load_user: bool = False,
    include_user_files: bool = False,
    order_by_desc: bool = False,
    source: DocumentSource | None = None,
) -> list[ConnectorCredentialPair]:
    if eager_load_user:
        assert (
            eager_load_credential
        ), "eager_load_credential must be True if eager_load_user is True"
    stmt = select(ConnectorCredentialPair).distinct()

    if eager_load_connector:
        stmt = stmt.options(selectinload(ConnectorCredentialPair.connector))

    if eager_load_credential:
        load_opts = selectinload(ConnectorCredentialPair.credential)
        if eager_load_user:
            load_opts = load_opts.joinedload(Credential.user)
        stmt = stmt.options(load_opts)

    stmt = _add_user_filters(stmt, user, get_editable)

    if source:
        stmt = stmt.join(ConnectorCredentialPair.connector).where(
            Connector.source == source.value
        )

    if ids:
        stmt = stmt.where(ConnectorCredentialPair.id.in_(ids))

    if not include_user_files:
        stmt = stmt.where(ConnectorCredentialPair.is_user_file.is_(False))

    if order_by_desc:
        stmt = stmt.order_by(desc(ConnectorCredentialPair.id))

    return list(db_session.scalars(stmt).unique().all())


# For use with our thread-level parallelism utils. Note that any relationships
# you wish to use MUST be eagerly loaded, as the session will not be available
# after this function to allow lazy loading.
def get_connector_credential_pairs_for_user_parallel(
    user: User | None,
    get_editable: bool = True,
    ids: list[int] | None = None,
    eager_load_connector: bool = False,
    eager_load_credential: bool = False,
    eager_load_user: bool = False,
    order_by_desc: bool = False,
    source: DocumentSource | None = None,
) -> list[ConnectorCredentialPair]:
    with get_session_with_current_tenant() as db_session:
        return get_connector_credential_pairs_for_user(
            db_session=db_session,
            user=user,
            get_editable=get_editable,
            ids=ids,
            eager_load_connector=eager_load_connector,
            eager_load_credential=eager_load_credential,
            eager_load_user=eager_load_user,
            order_by_desc=order_by_desc,
            source=source,
        )


def get_connector_credential_pairs(
    db_session: Session, ids: list[int] | None = None, include_user_files: bool = False
) -> list[ConnectorCredentialPair]:
    stmt = select(ConnectorCredentialPair).distinct()

    if ids:
        stmt = stmt.where(ConnectorCredentialPair.id.in_(ids))

    if not include_user_files:
        stmt = stmt.where(ConnectorCredentialPair.is_user_file != True)  # noqa: E712

    return list(db_session.scalars(stmt).all())


def add_deletion_failure_message(
    db_session: Session,
    cc_pair_id: int,
    failure_message: str,
) -> None:
    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    if not cc_pair:
        return
    cc_pair.deletion_failure_message = failure_message
    db_session.commit()


def get_cc_pair_groups_for_ids(
    db_session: Session,
    cc_pair_ids: list[int],
) -> list[UserGroup__ConnectorCredentialPair]:
    stmt = select(UserGroup__ConnectorCredentialPair).distinct()
    stmt = stmt.outerjoin(
        ConnectorCredentialPair,
        UserGroup__ConnectorCredentialPair.cc_pair_id == ConnectorCredentialPair.id,
    )
    stmt = stmt.where(UserGroup__ConnectorCredentialPair.cc_pair_id.in_(cc_pair_ids))
    return list(db_session.scalars(stmt).all())


# For use with our thread-level parallelism utils. Note that any relationships
# you wish to use MUST be eagerly loaded, as the session will not be available
# after this function to allow lazy loading.
def get_cc_pair_groups_for_ids_parallel(
    cc_pair_ids: list[int],
) -> list[UserGroup__ConnectorCredentialPair]:
    with get_session_with_current_tenant() as db_session:
        return get_cc_pair_groups_for_ids(db_session, cc_pair_ids)


def get_connector_credential_pair_for_user(
    db_session: Session,
    connector_id: int,
    credential_id: int,
    user: User | None,
    include_user_files: bool = False,
    get_editable: bool = True,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair)
    stmt = _add_user_filters(stmt, user, get_editable)
    stmt = stmt.where(ConnectorCredentialPair.connector_id == connector_id)
    stmt = stmt.where(ConnectorCredentialPair.credential_id == credential_id)
    if not include_user_files:
        stmt = stmt.where(ConnectorCredentialPair.is_user_file != True)  # noqa: E712
    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def get_connector_credential_pair(
    db_session: Session,
    connector_id: int,
    credential_id: int,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair)
    stmt = stmt.where(ConnectorCredentialPair.connector_id == connector_id)
    stmt = stmt.where(ConnectorCredentialPair.credential_id == credential_id)
    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def get_connector_credential_pair_from_id_for_user(
    cc_pair_id: int,
    db_session: Session,
    user: User | None,
    get_editable: bool = True,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair).distinct()
    stmt = _add_user_filters(stmt, user, get_editable)
    stmt = stmt.where(ConnectorCredentialPair.id == cc_pair_id)
    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def verify_user_has_access_to_cc_pair(
    cc_pair_id: int,
    db_session: Session,
    user: User,
    get_editable: bool = True,
) -> bool:
    stmt = select(ConnectorCredentialPair.id)
    stmt = _add_user_filters(stmt, user, get_editable)
    stmt = stmt.where(ConnectorCredentialPair.id == cc_pair_id)
    result = db_session.execute(stmt)
    return result.scalars().first() is not None


def get_connector_credential_pair_from_id(
    db_session: Session,
    cc_pair_id: int,
    eager_load_connector: bool = False,
    eager_load_credential: bool = False,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair).distinct()
    stmt = stmt.where(ConnectorCredentialPair.id == cc_pair_id)

    if eager_load_credential:
        stmt = stmt.options(joinedload(ConnectorCredentialPair.credential))
    if eager_load_connector:
        stmt = stmt.options(joinedload(ConnectorCredentialPair.connector))

    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def get_connector_credential_pairs_for_source(
    db_session: Session,
    source: DocumentSource,
) -> list[ConnectorCredentialPair]:
    stmt = (
        select(ConnectorCredentialPair)
        .join(ConnectorCredentialPair.connector)
        .where(Connector.source == source)
    )
    return list(db_session.scalars(stmt).unique().all())


def get_last_successful_attempt_poll_range_end(
    cc_pair_id: int,
    earliest_index: float,
    search_settings: SearchSettings,
    db_session: Session,
) -> float:
    """Used to get the latest `poll_range_end` for a given connector and credential.

    This can be used to determine the next "start" time for a new index attempt.

    Note that the attempts time_started is not necessarily correct - that gets set
    separately and is similar but not exactly the same as the `poll_range_end`.
    """
    latest_successful_index_attempt = (
        db_session.query(IndexAttempt)
        .join(
            ConnectorCredentialPair,
            IndexAttempt.connector_credential_pair_id == ConnectorCredentialPair.id,
        )
        .filter(
            ConnectorCredentialPair.id == cc_pair_id,
            IndexAttempt.search_settings_id == search_settings.id,
            IndexAttempt.status == IndexingStatus.SUCCESS,
        )
        .order_by(IndexAttempt.poll_range_end.desc())
        .first()
    )
    if (
        not latest_successful_index_attempt
        or not latest_successful_index_attempt.poll_range_end
    ):
        return earliest_index

    return latest_successful_index_attempt.poll_range_end.timestamp()


"""Updates"""


def _update_connector_credential_pair(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    status: ConnectorCredentialPairStatus | None = None,
    net_docs: int | None = None,
    run_dt: datetime | None = None,
) -> None:
    # simply don't update last_successful_index_time if run_dt is not specified
    # at worst, this would result in re-indexing documents that were already indexed
    if run_dt is not None:
        cc_pair.last_successful_index_time = run_dt
    if net_docs is not None:
        cc_pair.total_docs_indexed += net_docs
    if status is not None:
        cc_pair.status = status
    if cc_pair.is_user_file:
        cc_pair.status = ConnectorCredentialPairStatus.PAUSED

    db_session.commit()


def update_connector_credential_pair_from_id(
    db_session: Session,
    cc_pair_id: int,
    status: ConnectorCredentialPairStatus | None = None,
    net_docs: int | None = None,
    run_dt: datetime | None = None,
) -> None:
    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    if not cc_pair:
        logger.warning(
            f"Attempted to update pair for Connector Credential Pair '{cc_pair_id}'"
            f" but it does not exist"
        )
        return

    _update_connector_credential_pair(
        db_session=db_session,
        cc_pair=cc_pair,
        status=status,
        net_docs=net_docs,
        run_dt=run_dt,
    )


def update_connector_credential_pair(
    db_session: Session,
    connector_id: int,
    credential_id: int,
    status: ConnectorCredentialPairStatus | None = None,
    net_docs: int | None = None,
    run_dt: datetime | None = None,
) -> None:
    cc_pair = get_connector_credential_pair(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
    )
    if not cc_pair:
        logger.warning(
            f"Attempted to update pair for connector id {connector_id} "
            f"and credential id {credential_id}"
        )
        return

    _update_connector_credential_pair(
        db_session=db_session,
        cc_pair=cc_pair,
        status=status,
        net_docs=net_docs,
        run_dt=run_dt,
    )


def set_cc_pair_repeated_error_state(
    db_session: Session,
    cc_pair_id: int,
    in_repeated_error_state: bool,
) -> None:
    stmt = (
        update(ConnectorCredentialPair)
        .where(ConnectorCredentialPair.id == cc_pair_id)
        .values(in_repeated_error_state=in_repeated_error_state)
    )
    db_session.execute(stmt)
    db_session.commit()


def delete_connector_credential_pair__no_commit(
    db_session: Session,
    connector_id: int,
    credential_id: int,
) -> None:
    stmt = delete(ConnectorCredentialPair).where(
        ConnectorCredentialPair.connector_id == connector_id,
        ConnectorCredentialPair.credential_id == credential_id,
    )
    db_session.execute(stmt)


def associate_default_cc_pair(db_session: Session) -> None:
    existing_association = (
        db_session.query(ConnectorCredentialPair)
        .filter(
            ConnectorCredentialPair.connector_id == 0,
            ConnectorCredentialPair.credential_id == 0,
        )
        .one_or_none()
    )
    if existing_association is not None:
        return

    # DefaultCCPair has id 1 since it is the first CC pair created
    # It is DEFAULT_CC_PAIR_ID, but can't set it explicitly because it messed with the
    # auto-incrementing id
    association = ConnectorCredentialPair(
        connector_id=0,
        credential_id=0,
        access_type=AccessType.PUBLIC,
        name="DefaultCCPair",
        status=ConnectorCredentialPairStatus.ACTIVE,
    )
    db_session.add(association)
    db_session.commit()


def _relate_groups_to_cc_pair__no_commit(
    db_session: Session,
    cc_pair_id: int,
    user_group_ids: list[int] | None = None,
) -> None:
    if not user_group_ids:
        return

    for group_id in user_group_ids:
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group_id, cc_pair_id=cc_pair_id
            )
        )


def add_credential_to_connector(
    db_session: Session,
    user: User | None,
    connector_id: int,
    credential_id: int,
    cc_pair_name: str | None,
    access_type: AccessType,
    groups: list[int] | None,
    auto_sync_options: dict | None = None,
    initial_status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.SCHEDULED,
    last_successful_index_time: datetime | None = None,
    seeding_flow: bool = False,
    is_user_file: bool = False,
) -> StatusResponse:
    connector = fetch_connector_by_id(connector_id, db_session)

    # If we are in the seeding flow, we shouldn't need to check if the credential belongs to the user
    if seeding_flow:
        credential = fetch_credential_by_id(
            credential_id=credential_id,
            db_session=db_session,
        )
    else:
        credential = fetch_credential_by_id_for_user(
            credential_id,
            user,
            db_session,
            get_editable=False,
        )

    if connector is None:
        raise HTTPException(status_code=404, detail="Connector does not exist")

    if access_type == AccessType.SYNC:
        if not fetch_ee_implementation_or_noop(
            "onyx.external_permissions.sync_params",
            "check_if_valid_sync_source",
            noop_return_value=True,
        )(connector.source):
            raise HTTPException(
                status_code=400,
                detail=f"Connector of type {connector.source} does not support SYNC access type",
            )

    if credential is None:
        error_msg = (
            f"Credential {credential_id} does not exist or does not belong to user"
        )
        logger.error(error_msg)
        raise HTTPException(
            status_code=401,
            detail=error_msg,
        )

    existing_association = (
        db_session.query(ConnectorCredentialPair)
        .filter(
            ConnectorCredentialPair.connector_id == connector_id,
            ConnectorCredentialPair.credential_id == credential_id,
        )
        .one_or_none()
    )
    if existing_association is not None:
        return StatusResponse(
            success=False,
            message=f"Connector {connector_id} already has Credential {credential_id}",
            data=connector_id,
        )

    association = ConnectorCredentialPair(
        creator_id=user.id if user else None,
        connector_id=connector_id,
        credential_id=credential_id,
        name=cc_pair_name,
        status=initial_status,
        access_type=access_type,
        auto_sync_options=auto_sync_options,
        last_successful_index_time=last_successful_index_time,
        is_user_file=is_user_file,
    )
    db_session.add(association)
    db_session.flush()  # make sure the association has an id
    db_session.refresh(association)

    _relate_groups_to_cc_pair__no_commit(
        db_session=db_session,
        cc_pair_id=association.id,
        user_group_ids=groups,
    )

    db_session.commit()

    return StatusResponse(
        success=True,
        message=f"Creating new association between Connector {connector_id} and Credential {credential_id}",
        data=association.id,
    )


def remove_credential_from_connector(
    connector_id: int,
    credential_id: int,
    user: User | None,
    db_session: Session,
) -> StatusResponse[int]:
    connector = fetch_connector_by_id(connector_id, db_session)
    credential = fetch_credential_by_id_for_user(
        credential_id,
        user,
        db_session,
        get_editable=False,
    )

    if connector is None:
        raise HTTPException(status_code=404, detail="Connector does not exist")

    if credential is None:
        raise HTTPException(
            status_code=404,
            detail="Credential does not exist or does not belong to user",
        )

    association = get_connector_credential_pair_for_user(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
        user=user,
        get_editable=True,
    )

    if association is not None:
        fetch_ee_implementation_or_noop(
            "onyx.db.external_perm",
            "delete_user__ext_group_for_cc_pair__no_commit",
        )(
            db_session=db_session,
            cc_pair_id=association.id,
        )
        db_session.delete(association)
        db_session.commit()
        return StatusResponse(
            success=True,
            message=f"Credential {credential_id} removed from Connector",
            data=connector_id,
        )

    return StatusResponse(
        success=False,
        message=f"Connector already does not have Credential {credential_id}",
        data=connector_id,
    )


def fetch_indexable_standard_connector_credential_pair_ids(
    db_session: Session,
    active_cc_pairs_only: bool = True,
    limit: int | None = None,
) -> list[int]:
    stmt = select(ConnectorCredentialPair.id)

    # For regular indexing checks
    if active_cc_pairs_only:
        stmt = stmt.where(
            ConnectorCredentialPair.status.in_(
                ConnectorCredentialPairStatus.active_statuses()
            )
        )
    else:
        # For embedding swap checks, include PAUSED and exclude DELETING or INVALID
        stmt = stmt.where(
            ConnectorCredentialPair.status.in_(
                ConnectorCredentialPairStatus.indexable_statuses()
            )
        )

    # Exclude user files. NOTE: some cc pairs have null for is_user_file instead of False
    stmt = stmt.where(ConnectorCredentialPair.is_user_file.is_not(True))

    if limit:
        stmt = stmt.limit(limit)

    return list(db_session.scalars(stmt))


def fetch_indexable_user_file_connector_credential_pair_ids(
    db_session: Session,
    search_settings_id: int,
    limit: int | None = USER_FILE_INDEXING_LIMIT,
) -> list[int]:
    """
    Return up to `limit` user file connector_credential_pair IDs that still
    need indexing for the given `search_settings_id`

    A cc_pair is considered "needs indexing" if its most recent IndexAttempt
    for this search_settings_id is either:
        - Missing entirely (no attempts yet)
        - Present but not SUCCESS status

    Implementation details:
        - Uses a LEFT JOIN LATERAL subquery to fetch only the single newest attempt
            per cc_pair (`ORDER BY time_updated DESC LIMIT 1`), instead of joining all
            attempts. This avoids scanning thousands of historical attempts and
            keeps memory/CPU usage low
        - `ON TRUE` is required in the lateral join because the correlation to
            ConnectorCredentialPair.id happens inside the subquery itself
        - NOTE: Shares some redundant logic with should_index() (TODO: combine)

    Returns:
        list[int]: connector_credential_pair IDs that should be indexed next
    """
    latest_attempt = lateral(
        select(IndexAttempt.status)
        .where(
            IndexAttempt.connector_credential_pair_id == ConnectorCredentialPair.id,
            IndexAttempt.search_settings_id == search_settings_id,
        )
        .order_by(IndexAttempt.time_updated.desc())
        .limit(1)
    ).alias("latest_attempt")

    stmt = (
        select(ConnectorCredentialPair.id)
        .outerjoin(latest_attempt, true())  # ON TRUE, Postgres-style lateral join
        .where(
            ConnectorCredentialPair.is_user_file.is_(True),
            or_(
                latest_attempt.c.status.is_(None),  # no attempts at all
                latest_attempt.c.status != IndexingStatus.SUCCESS,  # latest != SUCCESS
            ),
        )
        .limit(limit)  # Always apply a limit when fetching user file cc pairs
    )

    return list(db_session.scalars(stmt))


def fetch_connector_credential_pair_for_connector(
    db_session: Session,
    connector_id: int,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair).where(
        ConnectorCredentialPair.connector_id == connector_id,
    )
    return db_session.scalar(stmt)


def resync_cc_pair(
    cc_pair: ConnectorCredentialPair,
    search_settings_id: int,
    db_session: Session,
) -> None:
    """
    Updates state stored in the connector_credential_pair table based on the
    latest index attempt for the given search settings.

    Args:
        cc_pair: ConnectorCredentialPair to resync
        search_settings_id: SearchSettings to use for resync
        db_session: Database session
    """

    def find_latest_index_attempt(
        connector_id: int,
        credential_id: int,
        only_include_success: bool,
        db_session: Session,
    ) -> IndexAttempt | None:
        query = (
            db_session.query(IndexAttempt)
            .join(
                ConnectorCredentialPair,
                IndexAttempt.connector_credential_pair_id == ConnectorCredentialPair.id,
            )
            .filter(
                ConnectorCredentialPair.connector_id == connector_id,
                ConnectorCredentialPair.credential_id == credential_id,
                IndexAttempt.search_settings_id == search_settings_id,
            )
        )

        if only_include_success:
            query = query.filter(IndexAttempt.status == IndexingStatus.SUCCESS)

        latest_index_attempt = query.order_by(desc(IndexAttempt.time_started)).first()

        return latest_index_attempt

    last_success = find_latest_index_attempt(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        only_include_success=True,
        db_session=db_session,
    )

    cc_pair.last_successful_index_time = (
        last_success.time_started if last_success else None
    )

    db_session.commit()
