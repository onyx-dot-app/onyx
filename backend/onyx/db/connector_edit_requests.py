"""Requests the connector-edit apply step puts on a cc-pair: a restart of its
index attempts, a prune, a prune after the next full re-index, and an access
change. Callers commit, so the requests land in the same transaction as the
edit."""

from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from onyx.db.document import mark_cc_pair_documents_for_sync__no_commit
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    IndexingMode,
    IndexingStatus,
)
from onyx.db.index_attempt import cancel_waiting_index_attempt__no_commit
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

_RESTART_CANCEL_REASON = "Connector configuration changed."

# A failed request retries after 5 minutes, doubling up to 6 hours.
_RETRY_BASE_SECONDS = 5 * 60
_RETRY_MAX_SECONDS = 6 * 60 * 60


class ReindexRequestBackoff(BaseModel):
    # Failed full re-index attempts that served the pending request.
    failure_count: int
    # DB time before which the beat does not retry the request.
    retry_after: datetime


def request_retry_delay(failure_count: int) -> timedelta:
    """The wait before retrying a request after ``failure_count`` (at least
    1) failed attempts: capped exponential, so a request never expires."""
    return timedelta(
        seconds=min(_RETRY_BASE_SECONDS * 2 ** (failure_count - 1), _RETRY_MAX_SECONDS)
    )


def _lock_cc_pair_for_request(
    db_session: Session, cc_pair_id: int
) -> ConnectorCredentialPair:
    cc_pair = db_session.execute(
        select(ConnectorCredentialPair)
        .where(ConnectorCredentialPair.id == cc_pair_id)
        .with_for_update()
        # Read the locked row, not a stale copy from the identity map.
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if cc_pair is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND, f"Connector credential pair {cc_pair_id} not found"
        )
    # The deletion stops the pair's attempts, and nothing indexes or prunes
    # it again.
    if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"Connector credential pair {cc_pair_id} is being deleted",
        )
    return cc_pair


def _restartable_attempts_select(cc_pair_id: int) -> Select[tuple[IndexAttempt]]:
    """The pair's active attempts that run with its config. All search
    settings and backfills too: they all run with the old config. The beat
    recreates a FUTURE attempt by its own rules."""
    return select(IndexAttempt).where(
        IndexAttempt.connector_credential_pair_id == cc_pair_id,
        IndexAttempt.status.in_(
            [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
        ),
        # A targeted reindex fetches named documents, not the config's
        # scope, and does not block the new attempt.
        IndexAttempt.targeted_reindex_job_id.is_(None),
    )


def has_restartable_attempt(db_session: Session, cc_pair_id: int) -> bool:
    """True when an edit applied now would restart an attempt of the pair."""
    return (
        db_session.scalar(select(_restartable_attempts_select(cc_pair_id).exists()))
        is True
    )


def request_attempt_restart__no_commit(
    db_session: Session, cc_pair_id: int, indexing_mode: IndexingMode
) -> list[str]:
    """Stops the pair's active index attempts, which run with the config from
    before an edit, and sets its indexing trigger so the beat creates a fresh
    attempt once they are terminal. Returns the Celery task ids to revoke
    after the commit.

    Unlike pause, it leaves the stop fence alone: the fence blocks every new
    attempt until it is cleared. A pending REINDEX trigger is kept. On a
    paused pair the trigger waits and fires on resume."""
    cc_pair = _lock_cc_pair_for_request(db_session, cc_pair_id)
    if cc_pair.indexing_trigger != IndexingMode.REINDEX:
        cc_pair.indexing_trigger = indexing_mode

    attempts = db_session.scalars(
        _restartable_attempts_select(cc_pair_id).with_for_update()
    ).all()

    task_ids: list[str] = []
    for attempt in attempts:
        # A first attempt held for the capability checks has no task to see a
        # cancel request. Ending it keeps it undispatched, so the next attempt
        # still waits for the checks.
        if attempt.celery_task_id is None and cancel_waiting_index_attempt__no_commit(
            db_session, attempt.id, reason=_RESTART_CANCEL_REASON
        ):
            continue
        # The docprocessing monitor turns this into CANCELED; docfetching
        # stops on its next status check.
        attempt.cancellation_requested = True
        if attempt.celery_task_id is not None:
            task_ids.append(attempt.celery_task_id)
    return task_ids


def request_prune__no_commit(db_session: Session, cc_pair_id: int) -> None:
    """Asks the pruning beat to prune the pair once, even without prune_freq.
    The request waits while the pair is not ACTIVE or a prune runs, and is
    cleared when a prune dispatched after it succeeds."""
    cc_pair = _lock_cc_pair_for_request(db_session, cc_pair_id)
    cc_pair.prune_requested_at = func.now()


def request_prune_after_reindex__no_commit(
    db_session: Session, cc_pair_id: int
) -> None:
    """Asks for a full re-index of the current index and a prune once one
    succeeds, so documents that left the scope are removed after the new
    crawl. Until then the pair stays due on the current index, even without
    refresh_freq, and every new attempt there is a full re-index, so a failed
    or canceled one passes the request on."""
    cc_pair = _lock_cc_pair_for_request(db_session, cc_pair_id)
    cc_pair.prune_after_reindex_requested_at = func.now()
    cc_pair.indexing_trigger = IndexingMode.REINDEX


def promote_prune_after_reindex_request__no_commit(
    db_session: Session, cc_pair_id: int, served_request_at: datetime
) -> None:
    """For a successful full re-index that served a prune-after-reindex
    request: requests the prune, and clears the pair's request unless a newer
    one replaced it."""
    db_session.execute(
        update(ConnectorCredentialPair)
        .where(ConnectorCredentialPair.id == cc_pair_id)
        .values(prune_requested_at=func.now())
    )
    db_session.execute(
        update(ConnectorCredentialPair)
        .where(
            ConnectorCredentialPair.id == cc_pair_id,
            ConnectorCredentialPair.prune_after_reindex_requested_at
            == served_request_at,
        )
        .values(prune_after_reindex_requested_at=None)
    )


def get_reindex_request_backoff(
    db_session: Session, cc_pair_id: int, search_settings_id: int
) -> ReindexRequestBackoff | None:
    """The backoff of the pair's pending prune-after-reindex request on these
    search settings, from the FAILED attempts that served it. None when none
    failed. A new request has a new time, so it starts with no backoff."""
    failure_count, last_failed_at = db_session.execute(
        select(func.count(IndexAttempt.id), func.max(IndexAttempt.time_updated))
        .join(
            ConnectorCredentialPair,
            ConnectorCredentialPair.id == IndexAttempt.connector_credential_pair_id,
        )
        .where(
            ConnectorCredentialPair.id == cc_pair_id,
            IndexAttempt.search_settings_id == search_settings_id,
            IndexAttempt.status == IndexingStatus.FAILED,
            IndexAttempt.prune_after_reindex_requested_at
            == ConnectorCredentialPair.prune_after_reindex_requested_at,
        )
    ).one()
    if failure_count == 0 or last_failed_at is None:
        return None
    return ReindexRequestBackoff(
        failure_count=failure_count,
        retry_after=last_failed_at + request_retry_delay(failure_count),
    )


def apply_access_change__no_commit(
    db_session: Session,
    cc_pair_id: int,
    access_type: AccessType,
    data_access_group_ids: set[int],
    visible_group_ids: set[int] | None,
) -> None:
    """Moves the pair to access_type with these data-access groups. It does
    not run the access gates; the caller runs validate_pairing_access first.

    Entering a perm-synced type from another type makes both permission syncs
    due and marks the pair as awaiting its first permission sync, so it grants
    nothing until its chunks carry the synced access. A source with no doc
    permission sync (Salesforce checks access after search) gets no mark,
    since nothing would clear it. Leaving one clears the
    mark and keeps the synced ACLs. SYNC <-> SYNC_RESTRICTED keeps the mark as
    it is: the ACLs are already synced. visible_group_ids is as in
    set_cc_pair_data_access_groups__no_commit; a type without data access
    loses all its groups."""
    has_data_access = access_type in AccessType.data_access_types()
    if data_access_group_ids and not has_data_access:
        raise ValueError(f"Access type {access_type} takes no data-access groups")

    cc_pair = _lock_cc_pair_for_request(db_session, cc_pair_id)
    previous_access_type = cc_pair.access_type
    cc_pair.access_type = access_type
    if access_type.is_perm_synced() and not previous_access_type.is_perm_synced():
        cc_pair.last_time_perm_sync = None
        cc_pair.last_time_external_group_sync = None
        if fetch_ee_implementation_or_noop(
            "onyx.external_permissions.sync_params",
            "source_requires_doc_sync",
            noop_return_value=False,
        )(cc_pair.connector.source):
            cc_pair.perm_sync_pending_since = func.now()
    elif not access_type.is_perm_synced():
        cc_pair.perm_sync_pending_since = None
    db_session.flush()

    fetch_ee_implementation_or_noop(
        "onyx.db.cc_pair_data_access", "set_cc_pair_data_access_groups__no_commit"
    )(
        db_session,
        cc_pair_id=cc_pair_id,
        requested_group_ids=data_access_group_ids,
        visible_group_ids=visible_group_ids if has_data_access else None,
    )
    fetch_ee_implementation_or_noop(
        "onyx.db.cc_pair_data_access", "assert_restricted_cc_pairs_keep_a_group"
    )(db_session, [cc_pair_id])

    if access_type != previous_access_type:
        # Rewrites the chunks' public field and group: entries.
        mark_cc_pair_documents_for_sync__no_commit(db_session, [cc_pair_id])
