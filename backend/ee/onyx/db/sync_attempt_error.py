from collections.abc import Collection

from sqlalchemy import ColumnElement, Select, case, func, select
from sqlalchemy.orm import Session

from ee.onyx.external_permissions.models import SyncEntityFailure
from onyx.configs.constants import DocumentSource
from onyx.db.cc_pair_run_resolution import (
    close_sync_attempt_errors_without_retry__no_commit,
    sync_attempt_error_is_open,
    sync_attempt_error_matches,
)
from onyx.db.enums import IndexAttemptErrorOrder, SyncEntityKind
from onyx.db.index_attempt import cap_failure_message
from onyx.db.models import ExternalGroupPermissionSyncAttempt, SyncAttemptError
from onyx.db.permission_sync_attempt import (
    lock_external_group_sync_attempt_if_owned,
    relevant_external_group_sync_attempts_filter,
)


def create_sync_attempt_error(
    db_session: Session,
    external_group_sync_attempt_id: int,
    cc_pair_id: int,
    failure: SyncEntityFailure,
) -> None:
    """Commits at once, so the session holds no transaction while the sync
    goes back to the source. Refused once the reaper has failed the attempt,
    like the group writes, so a lost attempt files no rows."""
    lock_external_group_sync_attempt_if_owned(
        external_group_sync_attempt_id, db_session
    )
    db_session.add(
        SyncAttemptError(
            external_group_sync_attempt_id=external_group_sync_attempt_id,
            connector_credential_pair_id=cc_pair_id,
            entity_kind=failure.kind,
            entity_id=failure.id,
            entity_name=failure.name,
            failure_message=cap_failure_message(failure.message),
        )
    )
    db_session.commit()


def _in_pair_history(cc_pair_id: int, source: DocumentSource) -> ColumnElement[bool]:
    """Rows of the group syncs the pair's run feed lists, so a source that
    syncs once for all its pairs shows its rows on each."""
    return SyncAttemptError.external_group_sync_attempt_id.in_(
        select(ExternalGroupPermissionSyncAttempt.id).where(
            relevant_external_group_sync_attempts_filter(cc_pair_id, source)
        )
    )


def _pair_sync_errors(
    stmt: Select,
    cc_pair_id: int,
    source: DocumentSource,
    unresolved_only: bool,
    attempt_id: int | None,
    entity_kind: SyncEntityKind | None,
    query: str | None,
) -> Select:
    """Narrows a ``SyncAttemptError`` select to the pair's rows, and optionally
    to open rows, one attempt, one entity kind, and ``query`` in the message,
    entity id or name."""
    stmt = stmt.where(_in_pair_history(cc_pair_id, source))
    if unresolved_only:
        stmt = stmt.where(sync_attempt_error_is_open())
    if attempt_id is not None:
        stmt = stmt.where(SyncAttemptError.external_group_sync_attempt_id == attempt_id)
    if entity_kind is not None:
        stmt = stmt.where(SyncAttemptError.entity_kind == entity_kind)
    if query:
        stmt = stmt.where(sync_attempt_error_matches(query))
    return stmt


def count_sync_attempt_errors_for_cc_pair(
    db_session: Session,
    cc_pair_id: int,
    source: DocumentSource,
    unresolved_only: bool,
    attempt_id: int | None,
    entity_kind: SyncEntityKind | None,
    query: str | None,
) -> int:
    stmt = _pair_sync_errors(
        select(func.count()).select_from(SyncAttemptError),
        cc_pair_id=cc_pair_id,
        source=source,
        unresolved_only=unresolved_only,
        attempt_id=attempt_id,
        entity_kind=entity_kind,
        query=query,
    )
    return db_session.scalar(stmt) or 0


def get_sync_attempt_errors_for_cc_pair(
    db_session: Session,
    cc_pair_id: int,
    source: DocumentSource,
    unresolved_only: bool,
    attempt_id: int | None,
    entity_kind: SyncEntityKind | None,
    query: str | None,
    page: int,
    page_size: int,
    order: IndexAttemptErrorOrder = IndexAttemptErrorOrder.TIME,
) -> list[SyncAttemptError]:
    """One page of the pair's failed users and groups in ``order``. The id
    breaks time ties, so rows never swap between pages."""
    stmt = _pair_sync_errors(
        select(SyncAttemptError),
        cc_pair_id=cc_pair_id,
        source=source,
        unresolved_only=unresolved_only,
        attempt_id=attempt_id,
        entity_kind=entity_kind,
        query=query,
    )
    if order is IndexAttemptErrorOrder.STATE:
        # Open rows first, then rows resolved without retry, the only closure.
        stmt = stmt.order_by(case((sync_attempt_error_is_open(), 0), else_=1))
    stmt = (
        stmt.order_by(SyncAttemptError.time_created.desc(), SyncAttemptError.id.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    return list(db_session.scalars(stmt).all())


def resolve_sync_attempt_errors_without_retry__no_commit(
    db_session: Session,
    cc_pair_id: int,
    source: DocumentSource,
    error_ids: Collection[int],
) -> list[int]:
    """Closes the chosen open rows the pair's feed lists without retry and
    returns the ids it closed. Other pairs' rows and closed rows are skipped."""
    if not error_ids:
        return []
    return close_sync_attempt_errors_without_retry__no_commit(
        db_session,
        SyncAttemptError.id,
        SyncAttemptError.id.in_(error_ids),
        _in_pair_history(cc_pair_id, source),
    )
