from datetime import datetime
from enum import Enum
from typing import TypeVarTuple
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import Select, and_, delete, desc, false, func, or_, select, update
from sqlalchemy.orm import Session, aliased, joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement

from onyx.auth.permissions import get_effective_permissions
from onyx.configs.constants import DEFAULT_CC_PAIR_ID, DocumentSource, NotificationType
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector_alerts import clear_connector_alerts__no_commit
from onyx.db.credentials import fetch_credential_by_id, fetch_credential_by_id_for_user
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    IndexingMode,
    Permission,
    ProcessingMode,
    SwitchoverType,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    DocumentByConnectorCredentialPair,
    IndexAttempt,
    IndexingStatus,
    SearchSettings,
    User,
    User__UserGroup,
    UserGroup,
    UserGroup__CCPairDataAccess,
    UserGroup__ConnectorCredentialPair,
)
from onyx.db.scoped_permissions import (
    scoped_group_ids_subquery,
    within_managed_scope_clause,
)
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import (
    fetch_ee_implementation_or_noop,
    fetch_versioned_implementation,
)

logger = setup_logger()

R = TypeVarTuple("R")
_CONNECTOR_STATE_QUERY_TIMEOUT = "7s"


def _build_user_group_cc_pair_access_clause(
    user_id: UUID,  # noqa: ARG001
) -> ColumnElement[bool]:
    """CE has no user groups. The EE version grants pairs where the user is in
    a data-access group.

    NOTE: EE version in ee.onyx.db.connector_credential_pair."""
    return false()


def build_user_cc_pair_access_filter(user_id: UUID) -> ColumnElement[bool]:
    """Pairs whose documents the user may see with no document ACL match
    ("open" pairs): PUBLIC pairs, and non-perm-synced pairs where the user owns
    the credential or is in a data-access group of the pair. Perm-synced pairs are
    never open; their documents need an ACL match. Does not exclude DELETING
    pairs."""
    credential_owner = (
        select(1)
        .select_from(Credential)
        .where(
            Credential.id == ConnectorCredentialPair.credential_id,
            Credential.user_id == user_id,
        )
        .correlate(ConnectorCredentialPair)
        .exists()
    )
    group_access_clause_fn = fetch_versioned_implementation(
        "onyx.db.connector_credential_pair", "_build_user_group_cc_pair_access_clause"
    )
    return or_(
        ConnectorCredentialPair.access_type == AccessType.PUBLIC,
        and_(
            ConnectorCredentialPair.access_type.notin_(AccessType.perm_synced_types()),
            or_(credential_owner, group_access_clause_fn(user_id)),
        ),
    )


class CCPairAccessSets(BaseModel):
    # Documents of these pairs are visible with no document ACL match.
    open_cc_pair_ids: set[int]
    # Documents of these pairs are visible if public or matching the user's ACL.
    acl_cc_pair_ids: set[int]


def get_cc_pair_access_sets_for_user(
    db_session: Session, user: User
) -> CCPairAccessSets:
    """The query-time access rule for a user, as sets of cc-pair ids.

    Open pairs follow build_user_cc_pair_access_filter; anonymous users get
    only PUBLIC pairs. Every user gets all perm-synced (SYNC, SYNC_RESTRICTED)
    pairs as ACL pairs, matching the chunk ACLs written today. DELETING pairs
    are left out of both sets."""
    open_clause = (
        ConnectorCredentialPair.access_type == AccessType.PUBLIC
        if user.is_anonymous
        else build_user_cc_pair_access_filter(user.id)
    )
    is_acl_pair = ConnectorCredentialPair.access_type.in_(
        AccessType.perm_synced_types()
    )
    rows = db_session.execute(
        select(ConnectorCredentialPair.id, is_acl_pair).where(
            ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING,
            or_(open_clause, is_acl_pair),
        )
    ).tuples()
    access_sets = CCPairAccessSets(open_cc_pair_ids=set(), acl_cc_pair_ids=set())
    for cc_pair_id, is_acl in rows:
        if is_acl:
            access_sets.acl_cc_pair_ids.add(cc_pair_id)
        else:
            access_sets.open_cc_pair_ids.add(cc_pair_id)
    return access_sets


class ConnectorType(str, Enum):
    STANDARD = "standard"
    USER_FILE = "user_file"


class ConnectorStateSnapshot(BaseModel):
    cc_pair_id: int
    cc_pair_name: str
    status: ConnectorCredentialPairStatus
    last_successful_index_time: datetime | None
    last_pruned: datetime | None
    last_time_perm_sync: datetime | None
    last_time_external_group_sync: datetime | None
    total_docs_indexed: int
    access_type: AccessType
    indexing_trigger: IndexingMode | None
    auto_sync_enabled: bool
    in_repeated_error_state: bool
    source: DocumentSource
    credential_id: int


def get_connector_state_snapshots(
    db_session: Session,
) -> list[ConnectorStateSnapshot]:
    db_session.execute(
        select(
            func.set_config("statement_timeout", _CONNECTOR_STATE_QUERY_TIMEOUT, True)
        )
    )
    rows = db_session.execute(
        select(
            ConnectorCredentialPair.id,
            ConnectorCredentialPair.name,
            ConnectorCredentialPair.status,
            ConnectorCredentialPair.last_successful_index_time,
            ConnectorCredentialPair.last_pruned,
            ConnectorCredentialPair.last_time_perm_sync,
            ConnectorCredentialPair.last_time_external_group_sync,
            ConnectorCredentialPair.total_docs_indexed,
            ConnectorCredentialPair.access_type,
            ConnectorCredentialPair.indexing_trigger,
            ConnectorCredentialPair.auto_sync_options,
            ConnectorCredentialPair.in_repeated_error_state,
            Connector.source,
            Credential.id,
        )
        .join(ConnectorCredentialPair.connector)
        .join(ConnectorCredentialPair.credential)
        .where(ConnectorCredentialPair.id != DEFAULT_CC_PAIR_ID)
    ).all()

    return [
        ConnectorStateSnapshot(
            cc_pair_id=cc_pair_id,
            cc_pair_name=cc_pair_name,
            status=status,
            last_successful_index_time=last_successful_index_time,
            last_pruned=last_pruned,
            last_time_perm_sync=last_time_perm_sync,
            last_time_external_group_sync=last_time_external_group_sync,
            total_docs_indexed=total_docs_indexed or 0,
            access_type=access_type,
            indexing_trigger=indexing_trigger,
            auto_sync_enabled=bool(auto_sync_options),
            in_repeated_error_state=in_repeated_error_state,
            source=source,
            credential_id=credential_id,
        )
        for (
            cc_pair_id,
            cc_pair_name,
            status,
            last_successful_index_time,
            last_pruned,
            last_time_perm_sync,
            last_time_external_group_sync,
            total_docs_indexed,
            access_type,
            indexing_trigger,
            auto_sync_options,
            in_repeated_error_state,
            source,
            credential_id,
        ) in rows
    ]


def _add_user_filters(
    stmt: Select[tuple[*R]], user: User, get_editable: bool = True
) -> Select[tuple[*R]]:
    user_permissions = get_effective_permissions(user)

    if Permission.MANAGE_CONNECTORS in user_permissions:
        return stmt

    # Reads: MANAGE_USER_GROUPS / MANAGE_DOCUMENT_SETS imply only READ_CONNECTORS, so
    # without this the attach pickers hide private pairs they aren't a member of.
    if not get_editable and Permission.READ_CONNECTORS in user_permissions:
        return stmt

    if user.is_anonymous:
        return stmt.where(ConnectorCredentialPair.access_type == AccessType.PUBLIC)

    stmt = stmt.distinct()
    UG__CCpair = aliased(UserGroup__ConnectorCredentialPair)
    User__UG = aliased(User__UserGroup)

    stmt = stmt.outerjoin(UG__CCpair).outerjoin(
        User__UG,
        User__UG.user_group_id == UG__CCpair.user_group_id,
    )

    where_clause = User__UG.user_id == user.id

    if get_editable:
        where_clause = within_managed_scope_clause(
            resource_id_col=ConnectorCredentialPair.id,
            junction_resource_col=UserGroup__ConnectorCredentialPair.cc_pair_id,
            junction_group_col=UserGroup__ConnectorCredentialPair.user_group_id,
            non_public_clause=ConnectorCredentialPair.access_type != AccessType.PUBLIC,
            managed_subq=scoped_group_ids_subquery(user),
            junction_live_clause=UserGroup__ConnectorCredentialPair.is_current.is_(
                True
            ),
        )
        # The scope clause needs >=1 managed group, so it can never match a groupless
        # pair — a permission-synced one has no group to sit in, which would lock its
        # creator out of what they just made. All three conditions are load-bearing:
        # creator alone would keep them editing it after it is published or moved into
        # groups they don't manage.
        has_live_group = (
            select(UserGroup__ConnectorCredentialPair.cc_pair_id)
            .where(
                UserGroup__ConnectorCredentialPair.cc_pair_id
                == ConnectorCredentialPair.id,
                UserGroup__ConnectorCredentialPair.is_current.is_(True),
            )
            .exists()
        )
        where_clause |= and_(
            ConnectorCredentialPair.creator_id == user.id,
            ConnectorCredentialPair.access_type != AccessType.PUBLIC,
            ~has_live_group,
        )
    else:
        where_clause |= ConnectorCredentialPair.access_type == AccessType.PUBLIC
        where_clause |= ConnectorCredentialPair.access_type == AccessType.SYNC

    return stmt.where(where_clause)


def get_manageable_cc_pairs_for_credentials(
    db_session: Session,
    user: User,
    credential_ids: list[int],
) -> list[ConnectorCredentialPair]:
    """The pairs using any of these credentials that the user can manage, with
    their connectors loaded. The single place that decides which connectors the
    credential usage hints may show."""
    stmt = (
        select(ConnectorCredentialPair)
        .distinct()
        .options(selectinload(ConnectorCredentialPair.connector))
        .where(ConnectorCredentialPair.credential_id.in_(credential_ids))
    )
    stmt = _add_user_filters(stmt, user, get_editable=True)
    return list(db_session.scalars(stmt).unique().all())


def get_connector_credential_pairs_for_user(
    db_session: Session,
    user: User,
    get_editable: bool = True,
    ids: list[int] | None = None,
    eager_load_connector: bool = False,
    eager_load_credential: bool = False,
    eager_load_user: bool = False,
    order_by_desc: bool = False,
    source: DocumentSource | None = None,
    processing_mode: ProcessingMode | None = ProcessingMode.REGULAR,
    defer_connector_config: bool = False,
) -> list[ConnectorCredentialPair]:
    """Get connector credential pairs for a user.

    Args:
        processing_mode: Filter by processing mode. Defaults to REGULAR to hide
            FILE_SYSTEM connectors from standard admin UI. Pass None to get all.
        defer_connector_config: If True, skips loading Connector.connector_specific_config
            to avoid fetching large JSONB blobs when they aren't needed.
    """
    if eager_load_user:
        assert eager_load_credential, (
            "eager_load_credential must be True if eager_load_user is True"
        )
    stmt = select(ConnectorCredentialPair).distinct()

    if eager_load_connector:
        connector_load = selectinload(ConnectorCredentialPair.connector)
        if defer_connector_config:
            connector_load = connector_load.defer(Connector.connector_specific_config)
        stmt = stmt.options(connector_load)

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

    if processing_mode is not None:
        stmt = stmt.where(ConnectorCredentialPair.processing_mode == processing_mode)

    if order_by_desc:
        stmt = stmt.order_by(desc(ConnectorCredentialPair.id))

    return list(db_session.scalars(stmt).unique().all())


# For use with our thread-level parallelism utils. Note that any relationships
# you wish to use MUST be eagerly loaded, as the session will not be available
# after this function to allow lazy loading.
def get_connector_credential_pairs_for_user_parallel(
    user: User,
    get_editable: bool = True,
    ids: list[int] | None = None,
    eager_load_connector: bool = False,
    eager_load_credential: bool = False,
    eager_load_user: bool = False,
    order_by_desc: bool = False,
    source: DocumentSource | None = None,
    processing_mode: ProcessingMode | None = ProcessingMode.REGULAR,
    defer_connector_config: bool = False,
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
            processing_mode=processing_mode,
            defer_connector_config=defer_connector_config,
        )


def get_connector_credential_pairs(
    db_session: Session, ids: list[int] | None = None
) -> list[ConnectorCredentialPair]:
    stmt = select(ConnectorCredentialPair).distinct()

    if ids:
        stmt = stmt.where(ConnectorCredentialPair.id.in_(ids))

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


def user_owns_groupless_cc_pair(
    cc_pair: ConnectorCredentialPair, db_session: Session, user: User
) -> bool:
    """Whether a pair is shared with nobody but its creator.

    Matches the creator fallback in _add_user_filters. The delete gate and the delete
    affordance both read this, so keep it the only definition — they must not drift.
    """
    if cc_pair.creator_id != user.id or cc_pair.access_type == AccessType.PUBLIC:
        return False
    return not any(
        relationship.is_current
        for relationship in get_cc_pair_groups_for_ids(
            db_session=db_session, cc_pair_ids=[cc_pair.id]
        )
    )


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
    user: User,
    get_editable: bool = True,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair)
    stmt = _add_user_filters(stmt, user, get_editable)
    stmt = stmt.where(ConnectorCredentialPair.connector_id == connector_id)
    stmt = stmt.where(ConnectorCredentialPair.credential_id == credential_id)
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
    user: User,
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


def get_cc_pair_ids_for_document(db_session: Session, document_id: str) -> set[int]:
    return set(
        db_session.scalars(
            select(ConnectorCredentialPair.id)
            .join(
                DocumentByConnectorCredentialPair,
                and_(
                    DocumentByConnectorCredentialPair.connector_id
                    == ConnectorCredentialPair.connector_id,
                    DocumentByConnectorCredentialPair.credential_id
                    == ConnectorCredentialPair.credential_id,
                ),
            )
            .where(DocumentByConnectorCredentialPair.id == document_id)
        )
    )


def get_cc_pair_ids_for_connector(db_session: Session, connector_id: int) -> set[int]:
    return set(
        db_session.scalars(
            select(ConnectorCredentialPair.id).where(
                ConnectorCredentialPair.connector_id == connector_id
            )
        )
    )


def get_non_deleting_cc_pair_ids(db_session: Session) -> list[int]:
    return list(
        db_session.scalars(
            select(ConnectorCredentialPair.id)
            .where(
                ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING
            )
            .order_by(ConnectorCredentialPair.id)
        )
    )


def verify_user_can_edit_all_cc_pairs(
    cc_pair_ids: set[int],
    db_session: Session,
    user: User,
) -> bool:
    # guard: issubset is vacuously true for an empty set, which would authorize anything
    if not cc_pair_ids:
        return False
    return cc_pair_ids.issubset(get_editable_cc_pair_ids(cc_pair_ids, db_session, user))


def get_editable_cc_pair_ids(
    cc_pair_ids: set[int],
    db_session: Session,
    user: User,
) -> set[int]:
    """The subset of ``cc_pair_ids`` the user may edit."""
    stmt = select(ConnectorCredentialPair.id)
    stmt = _add_user_filters(stmt, user, get_editable=True)
    stmt = stmt.where(ConnectorCredentialPair.id.in_(cc_pair_ids))
    return set(db_session.scalars(stmt))


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
    ignore_targeted_reindex: bool = True,
    ignore_synthetic_seed: bool = False,
) -> float:
    """Used to get the latest `poll_range_end` for a given connector and credential.

    This can be used to determine the next "start" time for a new index attempt.

    A reindex-port synthetic seed carries PRESENT's poll cursor and IS a valid resume
    point, so it is considered by default - the FUTURE's first connector attempt resumes
    from it instead of refetching full history. This differs from the count/latest helpers,
    which keep `ignore_synthetic_seed=True` because a seed is not a real indexing run.

    Note that the attempts time_started is not necessarily correct - that gets set
    separately and is similar but not exactly the same as the `poll_range_end`.
    """
    query = (
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
    )
    if ignore_targeted_reindex:
        query = query.filter(IndexAttempt.targeted_reindex_job_id.is_(None))
    if ignore_synthetic_seed:
        query = query.filter(IndexAttempt.is_synthetic_seed.is_(False))
    latest_successful_index_attempt = query.order_by(
        IndexAttempt.poll_range_end.desc()
    ).first()
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
        # Leaving INVALID means the connector was fixed: retire its alerts.
        if (
            cc_pair.status == ConnectorCredentialPairStatus.INVALID
            and status != ConnectorCredentialPairStatus.INVALID
        ):
            clear_connector_alerts__no_commit(
                db_session=db_session,
                cc_pair_id=cc_pair.id,
                notif_type=NotificationType.CONNECTOR_INVALID,
            )
        cc_pair.status = status

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
            "Attempted to update pair for Connector Credential Pair '%s' but it does not exist",
            cc_pair_id,
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
            "Attempted to update pair for connector id %s and credential id %s",
            connector_id,
            credential_id,
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

    assert_not_shared_with_default_group(db_session, user_group_ids)

    for group_id in user_group_ids:
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group_id, cc_pair_id=cc_pair_id
            )
        )


def _relate_data_access_groups_to_cc_pair__no_commit(
    db_session: Session,
    cc_pair_id: int,
    user_group_ids: list[int],
) -> None:
    if not user_group_ids:
        return

    assert_not_shared_with_default_group(db_session, user_group_ids)
    found_group_ids = set(
        db_session.scalars(
            select(UserGroup.id).where(
                UserGroup.id.in_(user_group_ids),
                UserGroup.is_up_for_deletion.is_(False),
            )
        )
    )
    if missing_group_ids := set(user_group_ids) - found_group_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"User group(s) not found: {sorted(missing_group_ids)}",
        )

    for group_id in set(user_group_ids):
        db_session.add(
            UserGroup__CCPairDataAccess(user_group_id=group_id, cc_pair_id=cc_pair_id)
        )


def add_credential_to_connector(
    db_session: Session,
    user: User,
    connector_id: int,
    credential_id: int,
    cc_pair_name: str,
    access_type: AccessType,
    groups: list[int] | None,
    data_access_group_ids: list[int] | None = None,
    auto_sync_options: dict | None = None,
    initial_status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.SCHEDULED,
    last_successful_index_time: datetime | None = None,
    seeding_flow: bool = False,
    processing_mode: ProcessingMode = ProcessingMode.REGULAR,
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
        )

    if connector is None:
        raise HTTPException(status_code=404, detail="Connector does not exist")

    if access_type == AccessType.SYNC:
        fetch_ee_implementation_or_noop(
            "onyx.utils.tier",
            "require_business_tier_for_sync_access",
            noop_return_value=None,
        )(access_type)
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
        creator_id=user.id,
        connector_id=connector_id,
        credential_id=credential_id,
        name=cc_pair_name,
        status=initial_status,
        access_type=access_type,
        auto_sync_options=auto_sync_options,
        last_successful_index_time=last_successful_index_time,
        processing_mode=processing_mode,
    )
    db_session.add(association)
    db_session.flush()  # make sure the association has an id
    db_session.refresh(association)

    _relate_groups_to_cc_pair__no_commit(
        db_session=db_session,
        cc_pair_id=association.id,
        user_group_ids=groups,
    )
    if access_type == AccessType.PRIVATE:
        # Callers that set only manage groups keep today's meaning: the
        # manage groups also get data access.
        _relate_data_access_groups_to_cc_pair__no_commit(
            db_session=db_session,
            cc_pair_id=association.id,
            user_group_ids=(
                data_access_group_ids
                if data_access_group_ids is not None
                else groups or []
            ),
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
    user: User,
    db_session: Session,
) -> StatusResponse[int]:
    connector = fetch_connector_by_id(connector_id, db_session)
    credential = fetch_credential_by_id_for_user(
        credential_id,
        user,
        db_session,
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

    if limit:
        stmt = stmt.limit(limit)

    return list(db_session.scalars(stmt))


def compute_wont_port_cc_pair_ids(
    db_session: Session, switchover_type: SwitchoverType
) -> list[int]:
    """cc_pairs whose data will NOT be carried into the new index for this reindex —
    the complement of the port scope. Derived from the SAME
    fetch_indexable_standard_connector_credential_pair_ids the reindex/swap use, so a
    change to what ports is reflected here automatically (no re-encoded status rules).
    Works out to INVALID always + PAUSED under ACTIVE_ONLY. Excludes DELETING (already
    being removed) and the default Ingestion cc_pair.
    """
    will_port = set(
        fetch_indexable_standard_connector_credential_pair_ids(
            db_session,
            active_cc_pairs_only=(switchover_type == SwitchoverType.ACTIVE_ONLY),
        )
    )
    stmt = select(ConnectorCredentialPair.id).where(
        ConnectorCredentialPair.id != DEFAULT_CC_PAIR_ID,
        ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING,
    )
    return sorted(cc_id for cc_id in db_session.scalars(stmt) if cc_id not in will_port)


def mark_cc_pairs_deleting_if_still_wont_port__no_commit(
    db_session: Session, cc_pair_ids: list[int]
) -> list[int]:
    """Atomically move the given cc_pairs to DELETING, but ONLY those still INVALID or
    PAUSED, returning the ids actually transitioned. Re-validation and the state change
    are one conditional UPDATE, so a connector re-activated (-> ACTIVE) after the reclaim
    consent set was captured is skipped, never clobbered into DELETING (Postgres rechecks
    the WHERE under the row lock). The caller fires connector deletion only for the
    returned ids and commits."""
    if not cc_pair_ids:
        return []
    stmt = (
        update(ConnectorCredentialPair)
        .where(
            ConnectorCredentialPair.id.in_(cc_pair_ids),
            ConnectorCredentialPair.status.in_(
                [
                    ConnectorCredentialPairStatus.INVALID,
                    ConnectorCredentialPairStatus.PAUSED,
                ]
            ),
        )
        .values(status=ConnectorCredentialPairStatus.DELETING)
        .returning(ConnectorCredentialPair.id)
    )
    transitioned_ids = list(db_session.execute(stmt).scalars().all())
    # Notifications have no foreign key to the cc_pair, so deleting one cascades nothing.
    # Without this the INVALID alert outlives the connector it points at, forever.
    for cc_pair_id in transitioned_ids:
        clear_connector_alerts__no_commit(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
            notif_type=NotificationType.CONNECTOR_INVALID,
        )
    return transitioned_ids


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
    commit: bool = True,
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
                IndexAttempt.targeted_reindex_job_id.is_(None),
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

    if commit:
        db_session.commit()
