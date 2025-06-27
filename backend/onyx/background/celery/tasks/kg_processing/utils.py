import time

from redis.lock import Lock as RedisLock

from onyx.configs.constants import OnyxRedisLocks
from onyx.db.document import check_for_documents_needing_kg_processing
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import is_kg_config_settings_enabled_valid
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.redis.redis_pool import get_redis_client


def is_kg_processing_blocked() -> bool:
    """Checks if there are any KG tasks in progress."""
    redis_client = get_redis_client()
    lock_beat: RedisLock = redis_client.lock(OnyxRedisLocks.KG_PROCESSING_LOCK)
    return lock_beat.locked()


def is_kg_processing_requirements_met() -> bool:
    """Checks that there are no other KG tasks in progress, KG is enabled, valid,
    and there are documents that need KG processing."""
    if is_kg_processing_blocked():
        return False

    kg_config = get_kg_config_settings()
    if not is_kg_config_settings_enabled_valid(kg_config):
        return False

    with get_session_with_current_tenant() as db_session:
        has_staging_entities = (
            db_session.query(KGEntityExtractionStaging).first() is not None
        )
        has_staging_relationships = (
            db_session.query(KGRelationshipExtractionStaging).first() is not None
        )
        return (
            check_for_documents_needing_kg_processing(
                db_session,
                kg_config.KG_COVERAGE_START_DATE,
                kg_config.KG_MAX_COVERAGE_DAYS,
            )
            or has_staging_entities
            or has_staging_relationships
        )


def is_kg_clustering_only_requirements_met() -> bool:
    """Checks that there are no other KG tasks in progress, KG is enabled, valid,
    and there are documents that need KG clustering."""
    if is_kg_processing_blocked():
        return False

    kg_config = get_kg_config_settings()
    if not is_kg_config_settings_enabled_valid(kg_config):
        return False

    # Check if there are any entries in the staging tables
    with get_session_with_current_tenant() as db_session:
        has_staging_entities = (
            db_session.query(KGEntityExtractionStaging).first() is not None
        )
        has_staging_relationships = (
            db_session.query(KGRelationshipExtractionStaging).first() is not None
        )

    return has_staging_entities or has_staging_relationships


def extend_lock(lock: RedisLock, timeout: int, last_lock_time: float) -> float:
    current_time = time.monotonic()
    if current_time - last_lock_time >= (timeout / 4):
        lock.reacquire()
        last_lock_time = current_time

    return last_lock_time
