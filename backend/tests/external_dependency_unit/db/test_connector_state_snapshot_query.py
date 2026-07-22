from datetime import datetime, timezone

from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_CC_PAIR_ID, DocumentSource
from onyx.db.connector_credential_pair import (
    ConnectorStateSnapshot,
    get_connector_state_snapshots,
)
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus, IndexingMode
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


def test_connector_state_snapshot_query(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    pairs = [make_cc_pair(db_session)]
    if pairs[0].id == DEFAULT_CC_PAIR_ID:
        pairs.append(make_cc_pair(db_session))
    pair = pairs[-1]
    timestamp = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
    pair.last_successful_index_time = timestamp
    pair.last_pruned = timestamp
    pair.last_time_perm_sync = timestamp
    pair.last_time_external_group_sync = timestamp
    pair.total_docs_indexed = 17
    pair.access_type = AccessType.SYNC
    pair.indexing_trigger = IndexingMode.UPDATE
    pair.auto_sync_options = {"enabled": True}
    pair.in_repeated_error_state = True
    db_session.commit()

    try:
        snapshot = next(
            item
            for item in get_connector_state_snapshots(db_session)
            if item.cc_pair_id == pair.id
        )
        assert snapshot == ConnectorStateSnapshot(
            cc_pair_id=pair.id,
            cc_pair_name=pair.name,
            status=ConnectorCredentialPairStatus.ACTIVE,
            last_successful_index_time=timestamp,
            last_pruned=timestamp,
            last_time_perm_sync=timestamp,
            last_time_external_group_sync=timestamp,
            total_docs_indexed=17,
            access_type=AccessType.SYNC,
            indexing_trigger=IndexingMode.UPDATE,
            auto_sync_enabled=True,
            in_repeated_error_state=True,
            source=DocumentSource.MOCK_CONNECTOR,
            credential_id=pair.credential_id,
        )
    finally:
        db_session.rollback()
        for created_pair in reversed(pairs):
            cleanup_cc_pair(db_session, created_pair)
