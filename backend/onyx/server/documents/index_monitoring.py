"""The indexing status page's fleet-wide reads: every pair the caller can read
as one population, where the pair routes in cc_pair.py read one pair."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.configs.constants import DEFAULT_CC_PAIR_ID
from onyx.db.cc_pair_runs import count_pairs_indexing
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
    get_connector_credential_pairs_for_user,
)
from onyx.db.document import get_document_counts_for_cc_pairs
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import ConnectorCredentialPair, User
from onyx.server.documents.cc_pair_throughput import throughput_of
from onyx.server.documents.models import (
    CCPairThroughputWindow,
    ConnectorCredentialPairIdentifier,
    IndexingOverviewResponse,
)

router = APIRouter(prefix="/manage/admin/index-monitoring")


def _readable_cc_pairs(
    db_session: Session, user: User
) -> dict[int, ConnectorCredentialPair]:
    """Every pair the caller can read, by id. Neither access level contains the
    other for a scoped manager, so both are read. An admin reads all at once."""
    levels = (
        [CCPairAccessLevel.READ]
        if has_global_permission(user, Permission.MANAGE_CONNECTORS)
        else [CCPairAccessLevel.READ, CCPairAccessLevel.OPERATE]
    )
    pairs: dict[int, ConnectorCredentialPair] = {}
    for level in levels:
        for cc_pair in get_connector_credential_pairs_for_user(
            db_session,
            user,
            level,
            eager_load_connector=True,
            eager_load_credential=True,
            eager_load_user=True,
            defer_connector_config=True,
        ):
            # The ingestion API's pair, which the status page never lists.
            if cc_pair.id == DEFAULT_CC_PAIR_ID:
                continue
            # A pair mid-deletion can have lost its connector or credential.
            if cc_pair.connector is None or cc_pair.credential is None:
                continue
            pairs[cc_pair.id] = cc_pair
    return pairs


def _docs_indexed_by_pair(
    db_session: Session, pairs: dict[int, ConnectorCredentialPair]
) -> dict[int, int]:
    """Indexed documents per pair id, counted for these pairs only."""
    counts = {
        (connector_id, credential_id): count
        for connector_id, credential_id, count in get_document_counts_for_cc_pairs(
            db_session,
            [
                ConnectorCredentialPairIdentifier(
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                )
                for cc_pair in pairs.values()
            ],
        )
    }
    return {
        cc_pair_id: counts.get((cc_pair.connector_id, cc_pair.credential_id), 0)
        for cc_pair_id, cc_pair in pairs.items()
    }


@router.get("/overview")
def get_indexing_overview(
    window: CCPairThroughputWindow = Query(CCPairThroughputWindow.HOURS_1),
    user: User = Depends(
        require_permission(Permission.READ_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> IndexingOverviewResponse:
    """The overview card's figures and throughput over the readable pairs."""
    pairs = _readable_cc_pairs(db_session, user)
    throughput = throughput_of(db_session, list(pairs), window)
    return IndexingOverviewResponse(
        indexing_connectors=count_pairs_indexing(db_session, list(pairs)),
        active_connectors=sum(
            1 for cc_pair in pairs.values() if cc_pair.status.is_active()
        ),
        recent_docs_indexed=sum(throughput.docs_indexed),
        total_docs_indexed=sum(_docs_indexed_by_pair(db_session, pairs).values()),
        throughput=throughput,
    )
