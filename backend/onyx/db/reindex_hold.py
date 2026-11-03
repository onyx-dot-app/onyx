"""The reindex hold: what a port-flow reindex waits for after every connector's port
is SUCCESS. Derived from index_attempt and port_attempt rows; nothing here writes.

Once the ports are done, PRESENT indexing stops and FUTURE catches up through its own
polling. A cc_pair *needs catch-up* when PRESENT indexed documents after the reindex
began (the port copy can be behind them) and no FUTURE attempt has since polled past
PRESENT's last run. FUTURE polls from its own cursor, so a successful attempt whose
window end (`poll_range_end`) is at or past PRESENT's last end and past the port's end
fetched every document PRESENT wrote in the meantime, with content at least as new.

A cc_pair whose FUTURE attempts keep failing is *abandoned*: the swap stops waiting
for it, and its documents changed since the reindex began lose their content hash at
the swap so the next poll re-indexes them into the new index. A paused cc_pair cannot
run FUTURE attempts (pausing cancels every attempt on the pair) and is handled the
same way without being abandoned.
"""

from collections.abc import Collection
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    REINDEX_HOLD_MAX_FUTURE_FAILURES,
    REINDEX_HOLD_MAX_SECONDS,
)
from onyx.configs.constants import DocumentSource
from onyx.db.connector_edit_requests import request_retry_delay
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import IndexingStatus, IndexModelStatus, SwitchoverType
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    IndexAttempt,
    PortAttempt,
    SearchSettings,
)
from onyx.db.port_attempt import (
    LatestPortRow,
    latest_port_by_cc_pair,
    reindex_hold_cc_pair_ids,
    reindex_port_cc_pair_ids,
)
from onyx.db.search_settings import get_current_search_settings

_SUCCESS_STATUSES = [status for status in IndexingStatus if status.is_successful()]
_TERMINAL_STATUSES = [status for status in IndexingStatus if status.is_terminal()]


class PairCatchUpState(BaseModel):
    """What one cc_pair still owes the swap. Times are DB time (UTC)."""

    cc_pair_id: int
    # ACTIVE / SCHEDULED / INITIAL_INDEXING. A paused pair cannot run FUTURE attempts.
    active: bool
    # Ingestion API pair: it writes both indexes itself, nothing to catch up.
    push_based: bool
    # When the reindex began for this pair: its seed's creation, else its first port
    # attempt's creation, else now. PRESENT writes before it are in the port copy.
    since: datetime
    # A PRESENT attempt is running, or is queued with a task (it will write).
    present_active: bool
    # When the pair's last terminal PRESENT attempt ended (targeted re-index excluded:
    # it writes both indexes). None when PRESENT never ran.
    last_present_end: datetime | None
    port_completed_at: datetime | None
    # Window end of the latest successful FUTURE poll, and when it ended.
    future_covered_through: datetime | None
    future_last_success_end: datetime | None
    # FUTURE attempts that ended without success, in a row, since the port completed.
    future_failed_streak: int
    # The beat starts no catch-up attempt before this.
    retry_after: datetime | None
    now: datetime

    @property
    def wrote_after_since(self) -> bool:
        return self.present_active or (
            self.last_present_end is not None and self.last_present_end > self.since
        )

    @property
    def caught_up(self) -> bool:
        """A successful FUTURE poll started after the port and after PRESENT's last
        attempt ended, so it saw everything PRESENT wrote during the reindex."""
        if self.port_completed_at is None or self.future_covered_through is None:
            return False
        watermark = max(
            self.port_completed_at, self.last_present_end or self.port_completed_at
        )
        return self.future_covered_through >= watermark

    @property
    def needs_catch_up(self) -> bool:
        return (
            self.active
            and not self.push_based
            and self.wrote_after_since
            and not self.caught_up
        )

    @property
    def abandoned(self) -> bool:
        """Catch-up gave up on this pair: the swap no longer waits for it."""
        if not self.needs_catch_up:
            return False
        if self.future_failed_streak >= REINDEX_HOLD_MAX_FUTURE_FAILURES:
            return True
        anchors = [
            t for t in (self.port_completed_at, self.future_last_success_end) if t
        ]
        if not anchors:
            return False
        return self.now - max(anchors) > timedelta(seconds=REINDEX_HOLD_MAX_SECONDS)

    @property
    def reset_hashes_at_swap(self) -> bool:
        """FUTURE never caught up with this pair and the swap proceeds anyway (paused,
        or abandoned): clear the hashes of what PRESENT wrote so the next poll
        re-indexes it."""
        return (
            self.wrote_after_since
            and not self.caught_up
            and (not self.active or self.abandoned)
        )

    @property
    def catch_up_due(self) -> bool:
        """The beat should start a FUTURE attempt for this pair now."""
        return (
            self.needs_catch_up
            and not self.present_active
            and not self.abandoned
            and (self.retry_after is None or self.now >= self.retry_after)
        )


class ReindexHoldState(BaseModel):
    """The hold for one beat. `finalizing` means every seeded connector's port is
    SUCCESS: PRESENT attempts stop and FUTURE catches up. Empty (not finalizing, no
    pairs) when there is no port-flow, non-INSTANT FUTURE."""

    future_id: int | None = None
    finalizing: bool = False
    pairs: dict[int, PairCatchUpState] = {}

    @property
    def hold_active(self) -> bool:
        return self.finalizing

    def pair(self, cc_pair_id: int) -> PairCatchUpState | None:
        return self.pairs.get(cc_pair_id)

    @property
    def catching_up_ids(self) -> list[int]:
        return [
            cc_pair_id
            for cc_pair_id, pair in self.pairs.items()
            if pair.needs_catch_up and not pair.abandoned
        ]

    @property
    def abandoned_ids(self) -> list[int]:
        return [cc_pair_id for cc_pair_id, pair in self.pairs.items() if pair.abandoned]


def _is_reindex_with_hold(future: SearchSettings | None) -> bool:
    return (
        future is not None
        and future.status == IndexModelStatus.FUTURE
        and future.use_port_flow
        and future.switchover_type != SwitchoverType.INSTANT
    )


def get_pair_catch_up_states(
    db_session: Session,
    future: SearchSettings,
    cc_pair_ids: Collection[int],
    *,
    now: datetime | None = None,
) -> dict[int, PairCatchUpState]:
    """Catch-up state of each cc_pair, from a fixed number of batched queries."""
    ids = list(cc_pair_ids)
    if not ids:
        return {}
    latest_ports = latest_port_by_cc_pair(db_session, future.id, ids)
    return _pair_states(db_session, future, ids, latest_ports, now=now)


def get_reindex_hold_state(
    db_session: Session,
    future: SearchSettings | None,
    *,
    now: datetime | None = None,
) -> ReindexHoldState:
    """The hold for this beat, over the whole port scope. Call it once per beat and
    pass it down; it runs several queries."""
    if future is None or not _is_reindex_with_hold(future):
        return ReindexHoldState()
    cc_pair_ids = reindex_port_cc_pair_ids(db_session, future.id)
    hold_ids = reindex_hold_cc_pair_ids(db_session, future.id, cc_pair_ids)
    latest_ports = latest_port_by_cc_pair(db_session, future.id, cc_pair_ids)
    finalizing = all(
        (row := latest_ports.get(cc_pair_id)) is not None and row.status.is_successful()
        for cc_pair_id in hold_ids
    )
    return ReindexHoldState(
        future_id=future.id,
        finalizing=finalizing,
        pairs=_pair_states(db_session, future, cc_pair_ids, latest_ports, now=now),
    )


def _pair_states(
    db_session: Session,
    future: SearchSettings,
    ids: list[int],
    latest_ports: dict[int, LatestPortRow],
    *,
    now: datetime | None,
) -> dict[int, PairCatchUpState]:
    db_now = now or get_db_current_time(db_session)
    present_id = get_current_search_settings(db_session).id

    pair_rows = {
        cc_pair_id: (status, connector_id, source)
        for cc_pair_id, status, connector_id, source in db_session.execute(
            select(
                ConnectorCredentialPair.id,
                ConnectorCredentialPair.status,
                Connector.id,
                Connector.source,
            )
            .join(Connector, Connector.id == ConnectorCredentialPair.connector_id)
            .where(ConnectorCredentialPair.id.in_(ids))
        )
    }
    seed_created: dict[int, datetime] = {
        cc_pair_id: created
        for cc_pair_id, created in db_session.execute(
            select(
                IndexAttempt.connector_credential_pair_id,
                func.min(IndexAttempt.time_created),
            )
            .where(
                IndexAttempt.search_settings_id == future.id,
                IndexAttempt.is_synthetic_seed.is_(True),
                IndexAttempt.connector_credential_pair_id.in_(ids),
            )
            .group_by(IndexAttempt.connector_credential_pair_id)
        )
        if cc_pair_id is not None
    }
    first_port_created: dict[int, datetime] = {
        cc_pair_id: created
        for cc_pair_id, created in db_session.execute(
            select(PortAttempt.cc_pair_id, func.min(PortAttempt.time_created))
            .where(
                PortAttempt.search_settings_id == future.id,
                PortAttempt.cc_pair_id.in_(ids),
            )
            .group_by(PortAttempt.cc_pair_id)
        )
        if cc_pair_id is not None
    }
    present_active_expr = or_(
        IndexAttempt.status == IndexingStatus.IN_PROGRESS,
        and_(
            IndexAttempt.status == IndexingStatus.NOT_STARTED,
            IndexAttempt.celery_task_id.isnot(None),
        ),
    )
    present_rows = {
        cc_pair_id: (last_end, bool(active))
        for cc_pair_id, last_end, active in db_session.execute(
            select(
                IndexAttempt.connector_credential_pair_id,
                func.max(IndexAttempt.end_time).filter(
                    IndexAttempt.targeted_reindex_job_id.is_(None)
                ),
                func.bool_or(present_active_expr),
            )
            .where(
                IndexAttempt.search_settings_id == present_id,
                IndexAttempt.connector_credential_pair_id.in_(ids),
                IndexAttempt.is_synthetic_seed.is_(False),
            )
            .group_by(IndexAttempt.connector_credential_pair_id)
        )
    }
    catch_up_attempt = and_(
        IndexAttempt.search_settings_id == future.id,
        IndexAttempt.connector_credential_pair_id.in_(ids),
        IndexAttempt.is_synthetic_seed.is_(False),
        IndexAttempt.is_backfill.is_(False),
        IndexAttempt.targeted_reindex_job_id.is_(None),
    )
    future_rows = {
        cc_pair_id: (covered_through, last_success_end)
        for cc_pair_id, covered_through, last_success_end in db_session.execute(
            select(
                IndexAttempt.connector_credential_pair_id,
                func.max(IndexAttempt.poll_range_end),
                func.max(IndexAttempt.end_time),
            )
            .where(catch_up_attempt, IndexAttempt.status.in_(_SUCCESS_STATUSES))
            .group_by(IndexAttempt.connector_credential_pair_id)
        )
    }
    # The newest terminal FUTURE attempts per pair, newest first: enough rows to
    # count a failed streak up to the abandon threshold.
    ranked = (
        select(
            IndexAttempt.connector_credential_pair_id.label("cc_pair_id"),
            IndexAttempt.status.label("status"),
            IndexAttempt.time_created.label("time_created"),
            IndexAttempt.end_time.label("end_time"),
            func.row_number()
            .over(
                partition_by=IndexAttempt.connector_credential_pair_id,
                order_by=(IndexAttempt.time_created.desc(), IndexAttempt.id.desc()),
            )
            .label("rn"),
        )
        .where(catch_up_attempt, IndexAttempt.status.in_(_TERMINAL_STATUSES))
        .subquery()
    )
    recent_terminal: dict[
        int, list[tuple[IndexingStatus, datetime, datetime | None]]
    ] = {}
    for cc_pair_id, status, time_created, end_time in db_session.execute(
        select(
            ranked.c.cc_pair_id,
            ranked.c.status,
            ranked.c.time_created,
            ranked.c.end_time,
        )
        .where(ranked.c.rn <= REINDEX_HOLD_MAX_FUTURE_FAILURES)
        .order_by(ranked.c.cc_pair_id, ranked.c.rn)
    ):
        recent_terminal.setdefault(cc_pair_id, []).append(
            (status, time_created, end_time)
        )

    states: dict[int, PairCatchUpState] = {}
    for cc_pair_id in ids:
        status, connector_id, source = pair_rows.get(cc_pair_id, (None, None, None))
        if status is None:
            continue
        port = latest_ports.get(cc_pair_id)
        port_completed_at = (
            port.time_completed
            if port is not None and port.status.is_successful()
            else None
        )
        # Leading run of FUTURE attempts that ended without success since the port
        # completed; the newest one's end sets the backoff.
        streak = 0
        latest_failed_end: datetime | None = None
        if port_completed_at is not None:
            for attempt_status, time_created, end_time in recent_terminal.get(
                cc_pair_id, []
            ):
                if attempt_status.is_successful() or time_created < port_completed_at:
                    break
                streak += 1
                latest_failed_end = latest_failed_end or end_time
        retry_after = (
            latest_failed_end + request_retry_delay(streak)
            if streak and latest_failed_end is not None
            else None
        )
        last_present_end, present_active = present_rows.get(cc_pair_id, (None, False))
        covered_through, last_success_end = future_rows.get(cc_pair_id, (None, None))
        since = (
            seed_created.get(cc_pair_id) or first_port_created.get(cc_pair_id) or db_now
        )
        states[cc_pair_id] = PairCatchUpState(
            cc_pair_id=cc_pair_id,
            active=status.is_active(),
            push_based=connector_id == 0 or source == DocumentSource.INGESTION_API,
            since=since,
            present_active=present_active,
            last_present_end=last_present_end,
            port_completed_at=port_completed_at,
            future_covered_through=covered_through,
            future_last_success_end=last_success_end,
            future_failed_streak=streak,
            retry_after=retry_after,
            now=db_now,
        )
    return states
