"""What a reindex swap clears so the new PRESENT re-indexes what FUTURE may lack.

PRESENT keeps indexing and stamping content hashes while the port copies its chunks
into FUTURE, so a document written after its copy is newer in PRESENT and the hash
gate would skip it after the swap. A FUTURE poll fetches at or after its window end,
so every change before the end of FUTURE's last successful poll already reached
FUTURE; only what PRESENT wrote after that point can be newer. The swap clears those
hashes (NULL never matches) and the next poll, which starts from that same window
end, re-indexes them. Read-only: derived from index_attempt and port_attempt rows.
"""

from collections.abc import Collection
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from onyx.configs.app_configs import POLL_CONNECTOR_OFFSET
from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import has_unresolved_entity_error
from onyx.db.enums import IndexingStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    IndexAttempt,
    PortAttempt,
    SearchSettings,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Poll windows overlap by this much to absorb source-side lag; the clear bound keeps
# the same margin, which also covers clock skew between workers.
_CLEAR_MARGIN = timedelta(minutes=POLL_CONNECTOR_OFFSET)
# A pair with neither a seed nor a port attempt cannot be placed in the reindex: clear
# everything it holds rather than nothing. The swap gate never passes such a pair.
_CLEAR_EVERYTHING_SINCE = datetime.fromtimestamp(0, tz=timezone.utc)


class PairClearBounds(BaseModel):
    """Which of one cc_pair's documents the swap clears. Times are DB time (UTC)."""

    cc_pair_id: int
    # Ingestion API pair: it writes both indexes itself, nothing to clear.
    push_based: bool
    # When the reindex began for this pair: its seed's creation, else its first port
    # attempt's creation. PRESENT writes before it are in the port copy.
    since: datetime
    # Window end of FUTURE's latest successful poll (seed, backfill and targeted
    # runs excluded). None when FUTURE never completed a poll for the pair.
    future_covered_through: datetime | None

    @property
    def clear_from(self) -> datetime:
        """Documents modified at or after this lose their hash at the swap."""
        if self.future_covered_through is None:
            return self.since
        return max(self.since, self.future_covered_through - _CLEAR_MARGIN)


def get_pair_clear_bounds(
    db_session: Session,
    future: SearchSettings,
    cc_pair_ids: Collection[int],
) -> dict[int, PairClearBounds]:
    """Clear bounds of each cc_pair, from a fixed number of batched queries."""
    ids = list(cc_pair_ids)
    if not ids:
        return {}

    pair_rows = {
        cc_pair_id: (connector_id, source)
        for cc_pair_id, connector_id, source in db_session.execute(
            select(ConnectorCredentialPair.id, Connector.id, Connector.source)
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
    # Same resume points as get_last_successful_attempt_poll_range_end: an attempt
    # that completed with an unresolved entity (folder, mailbox) error is not one,
    # since nothing says what that entity's window held.
    covered_through: dict[int, datetime] = {
        cc_pair_id: window_end
        for cc_pair_id, window_end in db_session.execute(
            select(
                IndexAttempt.connector_credential_pair_id,
                func.max(IndexAttempt.poll_range_end),
            )
            .where(
                IndexAttempt.search_settings_id == future.id,
                IndexAttempt.connector_credential_pair_id.in_(ids),
                or_(
                    IndexAttempt.status == IndexingStatus.SUCCESS,
                    and_(
                        IndexAttempt.status == IndexingStatus.COMPLETED_WITH_ERRORS,
                        ~has_unresolved_entity_error(),
                    ),
                ),
                IndexAttempt.is_synthetic_seed.is_(False),
                IndexAttempt.is_backfill.is_(False),
                IndexAttempt.targeted_reindex_job_id.is_(None),
                IndexAttempt.poll_range_end.isnot(None),
            )
            .group_by(IndexAttempt.connector_credential_pair_id)
        )
        if cc_pair_id is not None
    }

    bounds: dict[int, PairClearBounds] = {}
    for cc_pair_id in ids:
        row = pair_rows.get(cc_pair_id)
        if row is None:
            continue
        connector_id, source = row
        since = seed_created.get(cc_pair_id) or first_port_created.get(cc_pair_id)
        if since is None:
            logger.warning("cc_pair %s: no seed and no port; clearing all", cc_pair_id)
            since = _CLEAR_EVERYTHING_SINCE
        bounds[cc_pair_id] = PairClearBounds(
            cc_pair_id=cc_pair_id,
            push_based=connector_id == 0 or source == DocumentSource.INGESTION_API,
            since=since,
            future_covered_through=covered_through.get(cc_pair_id),
        )
    return bounds
