"""Requests the connector-edit apply step puts on a cc-pair: a restart of its
index attempts, a prune, and a prune after the next full re-index. Callers
commit, so the requests land in the same transaction as the edit."""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from onyx.db.enums import ConnectorCredentialPairStatus, IndexingMode, IndexingStatus
from onyx.db.index_attempt import cancel_waiting_index_attempt__no_commit
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_RESTART_CANCEL_REASON = "Connector configuration changed."


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

    # All search settings and backfills too: they all run with the old config.
    # The beat recreates a FUTURE attempt by its own rules.
    attempts = db_session.scalars(
        select(IndexAttempt)
        .where(
            IndexAttempt.connector_credential_pair_id == cc_pair_id,
            IndexAttempt.status.in_(
                [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
            ),
            # A targeted reindex fetches named documents, not the config's
            # scope, and does not block the new attempt.
            IndexAttempt.targeted_reindex_job_id.is_(None),
        )
        .with_for_update()
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
