"""Reindexing port machinery: the producer task plus the beat scheduler.

`run_port_attempt` (producer) drains one PortAttempt, copying a cc_pair's
documents PRESENT -> FUTURE (re-embedded under the new model) and committing a
per-batch cursor so a crash or stall resumes rather than restarts.

`check_for_port` (beat scheduler) runs once per tick: it fails stalled attempts,
then creates + enqueues a fresh PortAttempt for every in-scope cc_pair of a
use_port_flow FUTURE with pending work (a FAILED attempt resumes its cursor;
SUCCESS/CANCELED are left alone).
"""

import logging
import time
from collections.abc import Callable
from collections.abc import MutableMapping
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from uuid import UUID

from celery import Celery
from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import MAX_CONCURRENT_PORT_ATTEMPTS
from onyx.configs.app_configs import MAX_CONCURRENT_USER_FILE_PORT_ATTEMPTS
from onyx.configs.app_configs import MAX_CONSECUTIVE_PORT_FAILURES_BEFORE_PAUSE
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.connector_credential_pair import (
    fetch_indexable_standard_connector_credential_pair_ids,
)
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.document import filter_existing_cc_pair_document_ids
from onyx.db.document import get_document_ids_for_cc_pair_batch
from onyx.db.document import get_max_document_id_for_cc_pair
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import PortAttemptStatus
from onyx.db.enums import SwitchoverType
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.db.port_attempt import commit_port_cursor
from onyx.db.port_attempt import count_active_port_attempts
from onyx.db.port_attempt import count_consecutive_failed_port_attempts_no_progress
from onyx.db.port_attempt import create_port_attempt
from onyx.db.port_attempt import get_active_port_attempt
from onyx.db.port_attempt import get_latest_port_attempt
from onyx.db.port_attempt import get_port_attempt
from onyx.db.port_attempt import get_stale_in_progress_port_attempts
from onyx.db.port_attempt import mark_port_canceled
from onyx.db.port_attempt import mark_port_failed
from onyx.db.port_attempt import mark_port_in_progress
from onyx.db.port_attempt import mark_port_succeeded
from onyx.db.port_attempt import pause_port_attempt
from onyx.db.port_attempt import port_backfill_has_pending_work
from onyx.db.port_attempt import PortScope
from onyx.db.port_attempt import resume_paused_port_attempt
from onyx.db.port_attempt import touch_port_progress
from onyx.db.port_orphan_candidate import cleanup_stale_port_orphan_candidates
from onyx.db.port_orphan_candidate import clear_port_orphan_candidates
from onyx.db.port_orphan_candidate import get_port_orphan_candidate_doc_ids
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_search_settings_by_id
from onyx.db.search_settings import get_secondary_search_settings
from onyx.db.user_file import fetch_port_scope_user_ids
from onyx.db.user_file import filter_existing_user_file_ids
from onyx.db.user_file import get_max_user_file_id_for_user
from onyx.db.user_file import get_user_file_ids_for_user_batch
from onyx.db.user_file import user_file_port_scope_active
from onyx.document_index.opensearch.port_copy import PortCopier
from onyx.redis.redis_pool import get_redis_client

_PORT_SOFT_TIME_LIMIT = 60 * 30  # 30 minutes
_PORT_TIME_LIMIT = _PORT_SOFT_TIME_LIMIT + 60

_PORT_BATCH_MAX_RETRIES = 5
_PORT_BATCH_RETRY_SLEEP_S = 2


_PORT_STALL_THRESHOLD_SECONDS = 30 * 60  # 30 minutes

# Backoff before recreating a FAILED port stuck at the same cursor (durable error:
# bad/over-quota embed key, deleted model) so it doesn't recreate + re-embed every
# tick. First failure retries promptly (likely transient); repeated same-cursor
# failures back off exponentially, capped — a doomed port slows to hourly instead of
# burning embedding spend ~2880x/day.
_PORT_RETRY_BACKOFF_BASE_S = 30.0
_PORT_RETRY_BACKOFF_MAX_S = 60.0 * 60  # 1 hour


def port_attempt_scope(attempt: PortAttempt) -> PortScope:
    """A user attempt sets port_user_id; a connector attempt sets cc_pair_id."""
    return "user_file" if attempt.port_user_id is not None else "connector"


class _PortLogAdapter(logging.LoggerAdapter):
    """Prefix every port log line with its attempt + scope entity so concurrent ports
    are distinguishable in the shared worker log (mirrors the indexing
    [Index Attempt][CC Pair] prefix). The entity id is filled in once the attempt is
    read, so the few lines logged before that omit it."""

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        extra = self.extra or {}
        cc_pair_id = extra.get("cc_pair_id")
        port_user_id = extra.get("port_user_id")
        if cc_pair_id is not None:
            scope_prefix = f"[CC Pair: {cc_pair_id}] "
        elif port_user_id is not None:
            scope_prefix = f"[User: {port_user_id}] "
        else:
            scope_prefix = ""
        return (
            f"[Port Attempt: {extra.get('port_attempt_id')}] {scope_prefix}{msg}",
            kwargs,
        )


def _copy_batch_with_retry(
    copier: PortCopier,
    doc_ids: list[str],
    log: logging.LoggerAdapter,
    surviving_doc_ids: Callable[[], set[str]] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> tuple[int, bool]:
    """Copy one batch, retrying up to _PORT_BATCH_MAX_RETRIES on any failure.
    Returns (chunks written, aborted); aborted=True means should_abort stopped
    the copy mid-batch, so the caller must not advance its cursor past it.

    Re-raises the last error on exhaustion so the caller fails the attempt with
    the cursor still at the prior good batch. Retrying is safe because the write
    is idempotent (deterministic _id + create-only: re-creating an existing chunk
    is a benign 409, and the port never overwrites a forward/live write).

    The delay is fixed, not exponential: the embedder and OpenSearch layers
    already back off internally on rate-limits/transients, so a second curve here
    would just stack on theirs. This only guards a whole-pipeline hiccup that
    outlived them.
    """
    last_error: Exception | None = None
    for attempt_num in range(1, _PORT_BATCH_MAX_RETRIES + 1):
        try:
            return copier.copy_doc_batch(
                doc_ids,
                surviving_doc_ids=surviving_doc_ids,
                should_abort=should_abort,
            )
        except Exception as e:
            last_error = e
            log.warning(
                "Port batch attempt %d/%d failed: %s",
                attempt_num,
                _PORT_BATCH_MAX_RETRIES,
                e,
            )
            if attempt_num < _PORT_BATCH_MAX_RETRIES:
                time.sleep(_PORT_BATCH_RETRY_SLEEP_S)
    assert last_error is not None
    raise last_error


def _sweep_port_orphan_candidates(
    port_attempt_id: int,
    search_settings_id: int,
    cc_pair_id: int | None,
    port_user_id: UUID | None,
    copier: PortCopier,
    log: logging.LoggerAdapter,
) -> None:
    """Remove docs a create-only copy resurrected into the target during the port.

    create-only can't tell a just-deleted chunk from a never-written one, so a copy
    landing after a delete re-adds the doc. Deletes only the PORT-written chunks
    (written_by_port=true) of the recorded candidates in one delete-by-query — a
    legitimately re-added doc's forward-written chunks are unmarked and left intact, so
    no Postgres re-check is needed. Raises on a delete failure so the caller FAILs the
    attempt; check_for_port then resumes it (an empty re-copy) and re-sweeps.
    """
    with get_session_with_current_tenant() as db_session:
        candidate_ids = get_port_orphan_candidate_doc_ids(
            db_session, search_settings_id, cc_pair_id, port_user_id=port_user_id
        )
    if not candidate_ids:
        return

    deleted = copier.delete_port_written(candidate_ids)
    with get_session_with_current_tenant() as db_session:
        touch_port_progress(db_session, port_attempt_id)
        clear_port_orphan_candidates(
            db_session,
            search_settings_id,
            cc_pair_id,
            candidate_ids,
            port_user_id=port_user_id,
        )
        db_session.commit()
    if deleted:
        log.info("Swept %d resurrected orphan chunk(s) from the port target", deleted)


def run_port_attempt(port_attempt_id: int, celery_task_id: str | None = None) -> None:
    """Body of the port task, lifted out of @shared_task so tests call it
    directly. Resumes from the attempt's cursor and commits a new cursor after
    each batch, so a fresh attempt continues `WHERE document_id > cursor` rather
    than re-porting from the start.
    """
    log = _PortLogAdapter(
        task_logger,
        {
            "port_attempt_id": port_attempt_id,
            "celery_task_id": celery_task_id,
            "cc_pair_id": None,
            "port_user_id": None,
        },
    )

    # PortCopier must be built while the search settings are session-attached, so
    # do all setup here; the scan/embed/write loop below then holds no connection.
    with get_session_with_current_tenant() as db_session:
        attempt = get_port_attempt(db_session, port_attempt_id)
        if attempt is None:
            log.warning("PortAttempt not found, dropping task")
            return
        if attempt.status.is_resting():
            log.info(
                "PortAttempt already resting (%s), dropping task",
                attempt.status.value,
            )
            return
        if attempt.cancel_requested:
            # nothing written yet; ack immediately
            mark_port_canceled(db_session, port_attempt_id)
            log.info("Port cancel requested at startup; acknowledged and stopping")
            return

        cc_pair_id = attempt.cc_pair_id
        port_user_id = attempt.port_user_id
        # Replace extra (a read-only Mapping) so every later line carries the scope.
        log.extra = {
            **(log.extra or {}),
            "cc_pair_id": cc_pair_id,
            "port_user_id": port_user_id,
        }
        cursor = attempt.last_processed_doc_id
        up_to_doc_id = attempt.up_to_doc_id  # snapshot upper bound (None = unbounded)
        docs_ported = attempt.docs_ported or 0

        future_search_settings = get_search_settings_by_id(
            db_session, attempt.search_settings_id
        )
        if future_search_settings is None:
            mark_port_failed(
                db_session, port_attempt_id, error_msg="FUTURE search settings missing"
            )
            return
        # Source to copy from: the recorded backfill source when the target was
        # promoted mid-port (INSTANT) — "current" is now the target itself — else
        # the live PRESENT for a normal reindex.
        if future_search_settings.port_backfill_source_id is not None:
            present_search_settings = get_search_settings_by_id(
                db_session, future_search_settings.port_backfill_source_id
            )
            if present_search_settings is None:
                mark_port_failed(
                    db_session,
                    port_attempt_id,
                    error_msg="port backfill source settings missing",
                )
                return
        else:
            present_search_settings = get_current_search_settings(db_session)

        if not mark_port_in_progress(
            db_session, port_attempt_id, celery_task_id=celery_task_id
        ):
            # A supersede/cancel landed during startup; don't un-cancel and run on.
            log.info("PortAttempt went terminal during startup, dropping task")
            return

        try:
            copier = PortCopier(present_search_settings, future_search_settings)
        except Exception as e:
            log.exception("Failed to build port copier; marking FAILED")
            mark_port_failed(db_session, port_attempt_id, error_msg=str(e))
            return

    start_monotonic = time.monotonic()
    chunks_ported = 0

    # Per page: stop on terminal or cancel_requested, else heartbeat so the watchdog
    # doesn't fail a live port. Aborting stops writes; the ack (-> CANCELED) happens
    # at the batch-loop top, after this page, keeping cleanup the last writer.
    def _should_abort() -> bool:
        with get_session_with_current_tenant() as db_session:
            attempt = get_port_attempt(db_session, port_attempt_id)
            if (
                attempt is None
                or attempt.status.is_resting()
                or attempt.cancel_requested
            ):
                return True
            touch_port_progress(db_session, port_attempt_id)
            return False

    while True:
        # Fresh session per batch: frees the connection across the scan/embed/write,
        # and re-reads the row so a CANCEL or stall-FAIL committed elsewhere is seen.
        with get_session_with_current_tenant() as db_session:
            attempt = get_port_attempt(db_session, port_attempt_id)
            if attempt is None or attempt.status.is_resting():
                log.info("PortAttempt gone/resting, stopping")
                return
            if attempt.cancel_requested:
                # ack between batches, after our last write: this unblocks the waiting
                # deletion, so its cleanup writes strictly after us
                mark_port_canceled(db_session, port_attempt_id)
                log.info("Port cancel requested; acknowledged and stopping")
                return
            if port_user_id is not None:
                if not user_file_port_scope_active(db_session, port_user_id):
                    mark_port_canceled(db_session, port_attempt_id)
                    log.info("user gone, stopping port")
                    return
            elif cc_pair_id is not None:
                cc_pair = get_connector_credential_pair_from_id(db_session, cc_pair_id)
                if (
                    cc_pair is None
                    or cc_pair.status == ConnectorCredentialPairStatus.DELETING
                ):
                    # A deletion is waiting on us; ack now (between batches, after our
                    # last write) so it proceeds next tick, not after the watchdog.
                    mark_port_canceled(db_session, port_attempt_id)
                    log.info("cc_pair gone/deleting, stopping port")
                    return
            # Thread-pool tasks ignore celery's soft_time_limit, so enforce it here.
            # FAIL (not bare-return) so check_for_port resumes it promptly: a return
            # leaves the row IN_PROGRESS, which the scheduler treats as live until the
            # stall watchdog fails it a full window later. After the cancel/deleting
            # acks so those still win.
            if time.monotonic() - start_monotonic > _PORT_SOFT_TIME_LIMIT:
                mark_port_failed(
                    db_session,
                    port_attempt_id,
                    error_msg="soft time limit reached; yielding for reschedule",
                )
                log.info("Port soft time limit reached; failing for prompt resume")
                return
            if port_user_id is not None:
                doc_ids = get_user_file_ids_for_user_batch(
                    db_session,
                    port_user_id,
                    after_id=cursor,
                    limit=INDEX_BATCH_SIZE,
                    up_to_id=up_to_doc_id,
                )
            else:
                assert cc_pair_id is not None
                doc_ids = get_document_ids_for_cc_pair_batch(
                    db_session,
                    cc_pair_id,
                    after_doc_id=cursor,
                    limit=INDEX_BATCH_SIZE,
                    up_to_doc_id=up_to_doc_id,
                )

        if not doc_ids:
            break

        # Re-checked in the copier before each write: drop docs deleted mid-batch
        # so create-only doesn't resurrect them. Default-arg binds this batch's ids.
        def _surviving_doc_ids(_ids: list[str] = doc_ids) -> set[str]:
            with get_session_with_current_tenant() as db_session:
                if port_user_id is not None:
                    return filter_existing_user_file_ids(db_session, port_user_id, _ids)
                assert cc_pair_id is not None
                return filter_existing_cc_pair_document_ids(
                    db_session, cc_pair_id, _ids
                )

        try:
            batch_chunks, aborted = _copy_batch_with_retry(
                copier,
                doc_ids,
                log,
                surviving_doc_ids=_surviving_doc_ids,
                should_abort=_should_abort,
            )
        except Exception as e:
            log.exception("Port batch failed after retries; marking FAILED")
            with get_session_with_current_tenant() as db_session:
                mark_port_failed(db_session, port_attempt_id, error_msg=str(e))
            return

        chunks_ported += batch_chunks
        if aborted:
            # Tail was never written; advancing the cursor would skip it forever
            # on a FAILED resume. Loop back so the top does the terminal/cancel ack.
            continue

        cursor = doc_ids[-1]
        docs_ported += len(doc_ids)
        with get_session_with_current_tenant() as db_session:
            if not commit_port_cursor(
                db_session,
                port_attempt_id,
                last_processed_doc_id=cursor,
                docs_ported=docs_ported,
            ):
                log.info("PortAttempt terminalized mid-batch, stopping")
                return

    # Copy loop done and the cursor is committed at the final doc, so a FAILED resume
    # re-copies nothing. Before declaring success, sweep any doc deleted mid-port that a
    # create-only copy resurrected into the target.
    try:
        _sweep_port_orphan_candidates(
            port_attempt_id=port_attempt_id,
            search_settings_id=future_search_settings.id,
            cc_pair_id=cc_pair_id,
            port_user_id=port_user_id,
            copier=copier,
            log=log,
        )
    except Exception as e:
        log.exception("Port orphan sweep failed; marking FAILED")
        with get_session_with_current_tenant() as db_session:
            mark_port_failed(db_session, port_attempt_id, error_msg=str(e))
        return

    with get_session_with_current_tenant() as db_session:
        mark_port_succeeded(db_session, port_attempt_id)
    log.info("Port complete: %d docs, %d chunks", docs_ported, chunks_ported)


@shared_task(
    name=OnyxCeleryTask.RUN_PORT_ATTEMPT,
    soft_time_limit=_PORT_SOFT_TIME_LIMIT,
    time_limit=_PORT_TIME_LIMIT,
    bind=True,
)
def run_port_attempt_task(
    self: Task,
    *,
    port_attempt_id: int,
    tenant_id: str,  # noqa: ARG001  # consumed by TenantAwareTask wrapper
) -> None:
    run_port_attempt(
        port_attempt_id=port_attempt_id,
        celery_task_id=self.request.id,
    )


@shared_task(
    name=OnyxCeleryTask.RUN_USER_FILE_PORT_ATTEMPT,
    soft_time_limit=_PORT_SOFT_TIME_LIMIT,
    time_limit=_PORT_TIME_LIMIT,
    bind=True,
)
def run_user_file_port_attempt_task(
    self: Task,
    *,
    port_attempt_id: int,
    tenant_id: str,  # noqa: ARG001  # consumed by TenantAwareTask wrapper
) -> None:
    run_port_attempt(
        port_attempt_id=port_attempt_id,
        celery_task_id=self.request.id,
    )


def _fail_stalled_port_attempts(db_session: Session, lock_beat: RedisLock) -> None:
    """Fail every stale IN_PROGRESS attempt (all settings) past the stall threshold —
    a dead or self-yielded worker. Global on purpose: a supersede/promote (or a
    deletion's request_port_cancel) flags old attempts cancel_requested but leaves them
    IN_PROGRESS to ack, and those settings drop out of _resolve_port_target_settings —
    so if that worker dies unacked, only a global sweep frees the row, else connector
    deletion (which scans every settings) blocks forever. Also lets a fresh attempt
    resume the current target from the cursor."""
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=_PORT_STALL_THRESHOLD_SECONDS
    )
    for stale in get_stale_in_progress_port_attempts(db_session, stale_before):
        lock_beat.reacquire()
        fresh = get_port_attempt(db_session, stale.id)
        if fresh is None or fresh.status.is_terminal():
            continue
        task_logger.warning(
            "check_for_port: failing stalled PortAttempt %s (scope=%s cc_pair=%s user=%s)",
            stale.id,
            port_attempt_scope(stale),
            stale.cc_pair_id,
            stale.port_user_id,
        )
        mark_port_failed(
            db_session, stale.id, error_msg="stalled: no progress within threshold"
        )


def _port_retry_delay_seconds(consecutive_failures: int) -> float:
    """Exponential backoff (capped) for the consecutive same-cursor failure streak.
    The first failure retries immediately (likely transient); each repeat at the same
    cursor doubles the wait, up to the cap."""
    if consecutive_failures <= 1:
        return 0.0
    return min(
        _PORT_RETRY_BACKOFF_BASE_S * 2 ** (consecutive_failures - 2),
        _PORT_RETRY_BACKOFF_MAX_S,
    )


def _failed_port_ready_for_retry(
    db_session: Session,
    cc_pair_id: int | None,
    search_settings_id: int,
    latest: PortAttempt,
    *,
    port_user_id: UUID | None = None,
) -> bool:
    """Whether the backoff since the latest FAILED attempt has elapsed, so a port
    stuck failing at the same cursor isn't recreated (and re-embedded) every tick."""
    if latest.time_completed is None:
        return True
    failures = count_consecutive_failed_port_attempts_no_progress(
        db_session, cc_pair_id, search_settings_id, port_user_id=port_user_id
    )
    delay = _port_retry_delay_seconds(failures)
    return datetime.now(timezone.utc) >= latest.time_completed + timedelta(
        seconds=delay
    )


def _enqueue_run_port_attempt(
    celery_app: Celery,
    port_attempt_id: int,
    tenant_id: str,
    scope: PortScope = "connector",
) -> None:
    """Enqueue a port task on the scope's queue. The TTL means a task not consumed
    within BEAT_EXPIRES_DEFAULT is dropped; check_for_port re-issues it next tick."""
    if scope == "user_file":
        task_name = OnyxCeleryTask.RUN_USER_FILE_PORT_ATTEMPT
        queue = OnyxCeleryQueues.USER_FILE_PORT
    else:
        task_name = OnyxCeleryTask.RUN_PORT_ATTEMPT
        queue = OnyxCeleryQueues.PORT
    celery_app.send_task(
        task_name,
        kwargs={"port_attempt_id": port_attempt_id, "tenant_id": tenant_id},
        queue=queue,
        priority=OnyxCeleryPriority.MEDIUM,
        expires=BEAT_EXPIRES_DEFAULT,
    )


def _resolve_port_target_settings(db_session: Session) -> SearchSettings | None:
    """The settings the port should populate. A normal reindex ports the FUTURE
    (secondary). An INSTANT swap already promoted the FUTURE to PRESENT, so the port
    keeps backfilling that now-live index until every cc_pair is ported."""
    future = get_secondary_search_settings(db_session)
    if future is not None and future.use_port_flow:
        return future
    present = get_current_search_settings(db_session)
    if present.use_port_flow and present.port_backfill_source_id is not None:
        if port_backfill_has_pending_work(db_session, present.id):
            return present
        # Backfill drained: unpin the source so we stop re-checking a done job, the
        # source index can be reclaimed, and the reindex/vespa guards read "not
        # backfilling". Orphans were already swept per-attempt inside run_port_attempt.
        present.port_backfill_source_id = None
        db_session.commit()
    return None


def _schedule_scope_attempts(
    db_session: Session,
    celery_app: Celery,
    tenant_id: str,
    search_settings_id: int,
    scope: PortScope,
    entities: list[tuple[int | None, UUID | None]],
    cap: int,
    lock_beat: RedisLock,
) -> int:
    """Create / resume / recover port attempts for one scope's entities, returning the
    number of tasks enqueued. Identical logic for both scopes (connector cc_pairs, user
    files), keyed by each entity's (cc_pair_id, port_user_id) with exactly one set. The
    cap gates only NEW creation; recovery re-enqueues of already-active attempts always
    run (they add no load)."""
    created_new = 0
    reenqueued = 0
    at_cap = 0
    not_started_expired_before = datetime.now(timezone.utc) - timedelta(
        seconds=BEAT_EXPIRES_DEFAULT
    )
    active_attempts = count_active_port_attempts(
        db_session, search_settings_id, scope=scope
    )
    for cc_pair_id, port_user_id in entities:
        lock_beat.reacquire()
        active = get_active_port_attempt(
            db_session, cc_pair_id, search_settings_id, port_user_id=port_user_id
        )
        if active is not None:
            # IN_PROGRESS is the stall watchdog's job; a recent NOT_STARTED is still in
            # flight. Only re-issue a NOT_STARTED whose task has definitely expired --
            # idempotent (the run task's terminal-check + the active-unique index make a
            # re-send safe, and the original task is already gone, so no double-run).
            if (
                active.status == PortAttemptStatus.NOT_STARTED
                and active.time_updated < not_started_expired_before
            ):
                # Stamp before re-sending (the gate reads time_updated) so a down worker
                # gets one re-send per TTL window, not one per beat.
                active.time_updated = datetime.now(timezone.utc)
                db_session.commit()
                try:
                    _enqueue_run_port_attempt(celery_app, active.id, tenant_id, scope)
                    reenqueued += 1
                except Exception:
                    task_logger.exception(
                        "check_for_port: re-enqueue failed for stale NOT_STARTED "
                        "PortAttempt %s",
                        active.id,
                    )
            continue
        latest = get_latest_port_attempt(
            db_session, cc_pair_id, search_settings_id, port_user_id=port_user_id
        )
        # Auto-pause a unit stuck failing at the same cursor: after N consecutive
        # same-cursor failures, park it PAUSED for the operator instead of retrying it
        # forever. Evaluated before the cap gate so a cap-starved stuck unit still pauses
        # (else the operator banner is late to surface the very units it most needs to).
        if (
            latest is not None
            and latest.status == PortAttemptStatus.FAILED
            and count_consecutive_failed_port_attempts_no_progress(
                db_session, cc_pair_id, search_settings_id, port_user_id=port_user_id
            )
            >= MAX_CONSECUTIVE_PORT_FAILURES_BEFORE_PAUSE
        ):
            try:
                if pause_port_attempt(db_session, latest.id):
                    task_logger.warning(
                        "check_for_port: auto-paused after %d consecutive failures "
                        "(scope=%s cc_pair=%s user=%s)",
                        MAX_CONSECUTIVE_PORT_FAILURES_BEFORE_PAUSE,
                        scope,
                        cc_pair_id,
                        port_user_id,
                    )
            except Exception:
                # One unit's pause failing (DB blip) must not abort the whole tick.
                task_logger.exception(
                    "check_for_port: auto-pause failed (scope=%s cc_pair=%s user=%s)",
                    scope,
                    cc_pair_id,
                    port_user_id,
                )
            continue
        # At the concurrency cap: don't start new attempts (the remaining entities still
        # get recovery re-enqueues above next pass).
        if active_attempts >= cap:
            at_cap += 1
            continue
        # SUCCESS -> already ported; CANCELED/PAUSED -> stopped. Only a FAILED (or no)
        # attempt warrants a fresh run.
        if latest is not None and latest.status != PortAttemptStatus.FAILED:
            continue
        # Back off a port stuck failing at the same cursor (durable error) so it doesn't
        # recreate + re-embed every tick. A progressing port (cursor advanced) has a
        # streak of 1, so it isn't throttled.
        if latest is not None and not _failed_port_ready_for_retry(
            db_session,
            cc_pair_id,
            search_settings_id,
            latest,
            port_user_id=port_user_id,
        ):
            continue
        # Snapshot the upper bound on a fresh run; carry it across resumes so the whole
        # backfill targets the same doc set (the backlog at start).
        if latest is not None:
            resume_cursor = latest.last_processed_doc_id
            up_to_doc_id = latest.up_to_doc_id
        elif port_user_id is not None:
            resume_cursor = None
            up_to_doc_id = get_max_user_file_id_for_user(db_session, port_user_id)
        else:
            assert cc_pair_id is not None  # exactly-one scope (DB CHECK)
            resume_cursor = None
            up_to_doc_id = get_max_document_id_for_cc_pair(db_session, cc_pair_id)
        try:
            attempt = create_port_attempt(
                db_session,
                cc_pair_id,
                search_settings_id,
                resume_from_doc_id=resume_cursor,
                up_to_doc_id=up_to_doc_id,
                port_user_id=port_user_id,
            )
        except Exception:
            # One entity's failure (unique-index race, transient DB error) must not abort
            # the tick; the next tick retries it.
            task_logger.exception(
                "check_for_port: create failed (scope=%s cc_pair=%s user=%s)",
                scope,
                cc_pair_id,
                port_user_id,
            )
            continue
        try:
            _enqueue_run_port_attempt(celery_app, attempt.id, tenant_id, scope)
        except Exception:
            # Row is committed; on enqueue failure mark it FAILED so the next tick
            # recreates it (else an orphaned NOT_STARTED sticks).
            task_logger.exception(
                "check_for_port: enqueue failed; failing PortAttempt %s", attempt.id
            )
            mark_port_failed(db_session, attempt.id, error_msg="enqueue failed")
            continue
        created_new += 1
        active_attempts += 1
    if entities:
        task_logger.info(
            "port_scheduler scope=%s created=%d reenqueued=%d at_cap=%d",
            scope,
            created_new,
            reenqueued,
            at_cap,
        )
    return created_new + reenqueued


def run_check_for_port(tenant_id: str, celery_app: Celery) -> int | None:
    """Lifted out of check_for_port so tests can pass a mock celery app.

    Returns the number of attempts enqueued, or None if the lock was contended or
    there is no port-flow FUTURE.
    """
    redis_client = get_redis_client()
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHECK_PORT_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not lock_beat.acquire(blocking=False):
        return None

    tasks_created = 0
    try:
        with get_session_with_current_tenant() as db_session:
            # Before the early return: the sweep must run even when there's no current
            # target, else superseded settings' dead attempts strand (see the helper).
            _fail_stalled_port_attempts(db_session, lock_beat)

            port_settings = _resolve_port_target_settings(db_session)
            # Garbage-collect orphan candidates left by a superseded / permanently-FAILED
            # port (one that never reached the backstop). None target -> clears all.
            cleanup_stale_port_orphan_candidates(
                db_session, port_settings.id if port_settings else None
            )
            if port_settings is None:
                return None
            search_settings_id = port_settings.id

            include_paused = port_settings.switchover_type != SwitchoverType.ACTIVE_ONLY
            cc_pair_ids = fetch_indexable_standard_connector_credential_pair_ids(
                db_session, active_cc_pairs_only=not include_paused
            )
            tasks_created += _schedule_scope_attempts(
                db_session,
                celery_app,
                tenant_id,
                search_settings_id,
                "connector",
                [(cc_pair_id, None) for cc_pair_id in cc_pair_ids],
                MAX_CONCURRENT_PORT_ATTEMPTS,
                lock_beat,
            )

            # User files: a second scope with its own queue + cap (see USER_FILE_PORT).
            user_ids = fetch_port_scope_user_ids(db_session)
            tasks_created += _schedule_scope_attempts(
                db_session,
                celery_app,
                tenant_id,
                search_settings_id,
                "user_file",
                [(None, user_id) for user_id in user_ids],
                MAX_CONCURRENT_USER_FILE_PORT_ATTEMPTS,
                lock_beat,
            )
    finally:
        if lock_beat.owned():
            lock_beat.release()

    return tasks_created


def resume_paused_port_unit(
    celery_app: Celery,
    tenant_id: str,
    cc_pair_id: int | None,
    port_user_id: UUID | None,
    search_settings_id: int,
) -> bool:
    """Operator Resume: mint a fresh attempt from the paused cursor and enqueue it now,
    rather than waiting a TTL for the scheduler to notice the NOT_STARTED. Returns True if
    a unit was resumed (False if it wasn't PAUSED / the target was superseded / a
    concurrent resume won)."""
    scope: PortScope = "user_file" if port_user_id is not None else "connector"
    with get_session_with_current_tenant() as db_session:
        attempt = resume_paused_port_attempt(
            db_session,
            cc_pair_id=cc_pair_id,
            port_user_id=port_user_id,
            search_settings_id=search_settings_id,
        )
        if attempt is None:
            return False
        attempt_id = attempt.id
    try:
        _enqueue_run_port_attempt(celery_app, attempt_id, tenant_id, scope)
    except Exception:
        # The row is a committed NOT_STARTED; the scheduler re-enqueues it once its TTL
        # lapses, so a broker hiccup here only delays the resume, it doesn't lose it.
        task_logger.exception(
            "resume_paused_port_unit: enqueue failed for PortAttempt %s", attempt_id
        )
    return True


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_PORT,
    soft_time_limit=300,
    bind=True,
)
def check_for_port(self: Task, *, tenant_id: str) -> int | None:
    return run_check_for_port(tenant_id, self.app)
