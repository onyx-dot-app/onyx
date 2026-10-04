from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import TypeVarTuple
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import Select, and_, delete, desc, false, func, or_, select, update
from sqlalchemy.orm import Session, aliased, joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement

from onyx.auth.permissions import get_effective_permissions, has_permission
from onyx.configs.constants import DEFAULT_CC_PAIR_ID, DocumentSource, NotificationType
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector_alerts import clear_connector_alerts__no_commit
from onyx.db.credentials import fetch_credential_by_id, fetch_credential_by_id_for_user
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    ConnectorManageRole,
    IndexingMode,
    Permission,
    PermissionAuthority,
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
from onyx.db.scoped_permissions import scoped_group_ids_subquery
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


def build_user_acl_cc_pair_filter(user_id: UUID | None) -> ColumnElement[bool]:
    """Pairs whose documents the user may see on a document ACL match ("ACL"
    pairs): SYNC pairs, and SYNC_RESTRICTED pairs where the user is in a
    data-access group of the pair. Anonymous users (None) get only SYNC pairs.
    Does not exclude DELETING pairs."""
    is_sync = ConnectorCredentialPair.access_type == AccessType.SYNC
    if user_id is None:
        return is_sync
    group_access_clause_fn = fetch_versioned_implementation(
        "onyx.db.connector_credential_pair", "_build_user_group_cc_pair_access_clause"
    )
    return or_(
        is_sync,
        and_(
            ConnectorCredentialPair.access_type == AccessType.SYNC_RESTRICTED,
            group_access_clause_fn(user_id),
        ),
    )


def build_restricted_acl_guard(
    user_id: UUID | None,
    has_cc_pair: Callable[[ColumnElement[bool]], ColumnElement[bool]],
) -> ColumnElement[bool]:
    """For readers that match a document ACL without knowing which pair grants
    it. The match must not count for an item of a SYNC_RESTRICTED pair the user
    can't see, unless another pair of the item grants ACL access.

    has_cc_pair(clause) is an EXISTS over the item's pairs that match clause."""
    visible_acl_pair = and_(
        ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING,
        build_user_acl_cc_pair_filter(user_id),
    )
    hidden_restricted_pair = and_(
        ConnectorCredentialPair.access_type == AccessType.SYNC_RESTRICTED,
        ~visible_acl_pair,
    )
    return or_(~has_cc_pair(hidden_restricted_pair), has_cc_pair(visible_acl_pair))


def has_sync_restricted_cc_pairs(db_session: Session) -> bool:
    return bool(
        db_session.scalar(
            select(
                select(ConnectorCredentialPair.id)
                .where(
                    ConnectorCredentialPair.access_type == AccessType.SYNC_RESTRICTED
                )
                .exists()
            )
        )
    )


class CCPairAccessSets(BaseModel):
    # Documents of these pairs are visible with no document ACL match.
    open_cc_pair_ids: set[int]
    # Documents of these pairs are visible if public or matching the user's ACL.
    acl_cc_pair_ids: set[int]
    # SYNC_RESTRICTED pairs that grant the user nothing, DELETING ones included.
    hidden_restricted_cc_pair_ids: set[int]


def get_cc_pair_access_sets_for_user(
    db_session: Session, user: User
) -> CCPairAccessSets:
    """The query-time access rule for a user, as sets of cc-pair ids.

    Open pairs follow build_user_cc_pair_access_filter and ACL pairs follow
    build_user_acl_cc_pair_filter; anonymous users get only PUBLIC open pairs
    and SYNC ACL pairs. DELETING pairs are in neither set."""
    open_clause = (
        ConnectorCredentialPair.access_type == AccessType.PUBLIC
        if user.is_anonymous
        else build_user_cc_pair_access_filter(user.id)
    )
    acl_clause = build_user_acl_cc_pair_filter(None if user.is_anonymous else user.id)
    is_live = ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING
    is_restricted = ConnectorCredentialPair.access_type == AccessType.SYNC_RESTRICTED
    rows = db_session.execute(
        select(
            ConnectorCredentialPair.id,
            and_(is_live, acl_clause).label("is_acl"),
            and_(is_live, open_clause).label("is_open"),
        ).where(or_(and_(is_live, or_(open_clause, acl_clause)), is_restricted))
    ).tuples()
    access_sets = CCPairAccessSets(
        open_cc_pair_ids=set(),
        acl_cc_pair_ids=set(),
        hidden_restricted_cc_pair_ids=set(),
    )
    for cc_pair_id, is_acl, is_open in rows:
        if is_acl:
            access_sets.acl_cc_pair_ids.add(cc_pair_id)
        elif is_open:
            access_sets.open_cc_pair_ids.add(cc_pair_id)
        else:
            access_sets.hidden_restricted_cc_pair_ids.add(cc_pair_id)
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


class CCPairAccessLevel(str, Enum):
    """What the caller needs to do with a pair. READ is visibility; OPERATE and
    EDIT are management, granted by a manage role (see ConnectorManageRole)."""

    READ = "read"
    OPERATE = "operate"
    EDIT = "edit"


_ROLES_FOR_ACCESS_LEVEL: dict[CCPairAccessLevel, tuple[ConnectorManageRole, ...]] = {
    CCPairAccessLevel.OPERATE: (
        ConnectorManageRole.OPERATOR,
        ConnectorManageRole.EDITOR,
    ),
    CCPairAccessLevel.EDIT: (ConnectorManageRole.EDITOR,),
}


def _manage_access_clause(
    user: User, roles: tuple[ConnectorManageRole, ...]
) -> ColumnElement[bool]:
    """Scoped management of a pair, for a caller without global MANAGE_CONNECTORS.

    A scoped manager passes when a group they manage holds one of ``roles`` on the
    pair, for any access type. The creator of a pair with no manage group is its
    Editor, so a groupless permission-synced pair does not lock out its creator;
    that fallback stops once the pair is published or given a manage group."""
    live_manage_row = and_(
        UserGroup__ConnectorCredentialPair.cc_pair_id == ConnectorCredentialPair.id,
        UserGroup__ConnectorCredentialPair.is_current.is_(True),
    )
    has_manage_group = (
        select(UserGroup__ConnectorCredentialPair.cc_pair_id)
        .where(live_manage_row)
        .exists()
    )
    is_groupless_creator = and_(
        ConnectorCredentialPair.creator_id == user.id,
        ConnectorCredentialPair.access_type != AccessType.PUBLIC,
        ~has_manage_group,
    )
    if has_permission(user, Permission.MANAGE_CONNECTORS) is not (
        PermissionAuthority.SCOPED
    ):
        return is_groupless_creator

    has_role_in_managed_group = (
        select(UserGroup__ConnectorCredentialPair.cc_pair_id)
        .where(
            live_manage_row,
            UserGroup__ConnectorCredentialPair.role.in_(roles),
            UserGroup__ConnectorCredentialPair.user_group_id.in_(
                scoped_group_ids_subquery(user)
            ),
        )
        .exists()
    )
    return or_(has_role_in_managed_group, is_groupless_creator)


def _add_user_filters(
    stmt: Select[tuple[*R]], user: User, access_level: CCPairAccessLevel
) -> Select[tuple[*R]]:
    user_permissions = get_effective_permissions(user)

    if Permission.MANAGE_CONNECTORS in user_permissions:
        return stmt

    if access_level is not CCPairAccessLevel.READ:
        return stmt.where(
            _manage_access_clause(user, _ROLES_FOR_ACCESS_LEVEL[access_level])
        )

    # Reads: MANAGE_USER_GROUPS / MANAGE_DOCUMENT_SETS imply only READ_CONNECTORS, so
    # without this the attach pickers hide private pairs they aren't a member of.
    if Permission.READ_CONNECTORS in user_permissions:
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
    where_clause |= ConnectorCredentialPair.access_type == AccessType.PUBLIC
    where_clause |= build_user_acl_cc_pair_filter(user.id)

    return stmt.where(where_clause)


def get_manageable_cc_pairs_for_credentials(
    db_session: Session,
    user: User,
    credential_ids: list[int],
) -> list[ConnectorCredentialPair]:
    """The pairs using any of these credentials that the user can operate, with
    their connectors loaded. The single place that decides which connectors the
    credential usage hints may show."""
    stmt = (
        select(ConnectorCredentialPair)
        .distinct()
        .options(selectinload(ConnectorCredentialPair.connector))
        .where(ConnectorCredentialPair.credential_id.in_(credential_ids))
    )
    stmt = _add_user_filters(stmt, user, CCPairAccessLevel.OPERATE)
    return list(db_session.scalars(stmt).unique().all())


def get_connector_credential_pairs_for_user(
    db_session: Session,
    user: User,
    access_level: CCPairAccessLevel,
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

    stmt = _add_user_filters(stmt, user, access_level)

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
    access_level: CCPairAccessLevel,
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
            access_level=access_level,
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
    access_level: CCPairAccessLevel,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair)
    stmt = _add_user_filters(stmt, user, access_level)
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
    access_level: CCPairAccessLevel,
) -> ConnectorCredentialPair | None:
    stmt = select(ConnectorCredentialPair).distinct()
    stmt = _add_user_filters(stmt, user, access_level)
    stmt = stmt.where(ConnectorCredentialPair.id == cc_pair_id)
    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def verify_user_has_access_to_cc_pair(
    cc_pair_id: int,
    db_session: Session,
    user: User,
    access_level: CCPairAccessLevel,
) -> bool:
    stmt = select(ConnectorCredentialPair.id)
    stmt = _add_user_filters(stmt, user, access_level)
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


def select_cc_pair_ids_for_user(
    user: User, access_level: CCPairAccessLevel
) -> Select[tuple[int]]:
    """The ids of the pairs the user holds ``access_level`` on, as a statement to
    run or to use as a subquery."""
    return _add_user_filters(select(ConnectorCredentialPair.id), user, access_level)


def get_managed_cc_pair_ids(
    cc_pair_ids: set[int],
    db_session: Session,
    user: User,
    access_level: CCPairAccessLevel,
) -> set[int]:
    """The subset of ``cc_pair_ids`` the user holds ``access_level`` on."""
    stmt = select_cc_pair_ids_for_user(user, access_level).where(
        ConnectorCredentialPair.id.in_(cc_pair_ids)
    )
    return set(db_session.scalars(stmt))


def verify_user_can_manage_all_cc_pairs(
    cc_pair_ids: set[int],
    db_session: Session,
    user: User,
    access_level: CCPairAccessLevel,
) -> bool:
    # guard: issubset is vacuously true for an empty set, which would authorize anything
    if not cc_pair_ids:
        return False
    return cc_pair_ids.issubset(
        get_managed_cc_pair_ids(cc_pair_ids, db_session, user, access_level)
    )


def verify_user_can_edit_connector(
    connector_id: int, db_session: Session, user: User
) -> bool:
    """A connector carries no groups, so its pairs decide: the user must be an Editor
    of every pair on it. A connector with no pairs has no Editor, so only global
    MANAGE_CONNECTORS passes."""
    if Permission.MANAGE_CONNECTORS in get_effective_permissions(user):
        return True
    return verify_user_can_manage_all_cc_pairs(
        get_cc_pair_ids_for_connector(db_session, connector_id),
        db_session,
        user,
        CCPairAccessLevel.EDIT,
    )


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
    manage_access: dict[int, ConnectorManageRole],
) -> None:
    if not manage_access:
        return

    assert_not_shared_with_default_group(db_session, manage_access.keys())

    for group_id, role in manage_access.items():
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group_id, cc_pair_id=cc_pair_id, role=role
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
    manage_access: dict[int, ConnectorManageRole],
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

    if access_type.is_perm_synced():
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
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Connector of type {connector.source} does not support permission sync",
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
        manage_access=manage_access,
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
                else list(manage_access)
            ),
        )
    elif access_type == AccessType.SYNC_RESTRICTED:
        # With no data-access group the pair would be visible to nobody.
        if not data_access_group_ids:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "A restricted connector needs at least one data-access group.",
            )
        _relate_data_access_groups_to_cc_pair__no_commit(
            db_session=db_session,
            cc_pair_id=association.id,
            user_group_ids=data_access_group_ids,
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
        access_level=CCPairAccessLevel.EDIT,
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
