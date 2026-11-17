from sqlalchemy.orm import Session

from onyx.db.enums import SyncType
from onyx.db.sync_record import cleanup_sync_records
from onyx.redis.redis_connector import RedisConnector


def reset_prune_and_cancel_sync_record(
    redis_connector: RedisConnector, db_session: Session
) -> None:
    """Abandons the pair's prune: its open PRUNING sync record ends CANCELED and
    the fence is reset. The pair's prune request stays, so a later prune
    serves it. The record closes first, so a failed write keeps the fence up."""
    cleanup_sync_records(
        db_session=db_session,
        entity_id=redis_connector.cc_pair_id,
        sync_type=SyncType.PRUNING,
    )
    redis_connector.prune.reset()
