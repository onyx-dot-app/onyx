"""Redis cache operations for hierarchy node ancestor resolution.

This module provides a Redis-based cache for hierarchy node parent relationships,
enabling fast ancestor path resolution without repeated database queries.

The cache stores node_id -> parent_id mappings for all hierarchy nodes of a given
source type. When resolving ancestors for a document, we walk up the tree using
Redis lookups instead of database queries.

Cache Strategy:
- Nodes are cached per source type with a 6-hour TTL
- During docfetching, nodes are added to cache as they're upserted to Postgres
- If the cache is stale (TTL expired during long-running job), one worker does
  a full refresh from DB while others wait
- If a node is still not found after refresh, we log an error and fall back to
  using only the SOURCE-type node as the ancestor
"""

from typing import TYPE_CHECKING

from pydantic import BaseModel
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import ensure_source_node_exists as db_ensure_source_node_exists
from onyx.db.hierarchy import get_all_hierarchy_nodes_for_source
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.db.models import HierarchyNode as DBHierarchyNode

logger = setup_logger()

# Cache TTL: 6 hours in seconds
HIERARCHY_CACHE_TTL_SECONDS = 6 * 60 * 60

# Lock timeout for cache refresh: 5 minutes
HIERARCHY_CACHE_LOCK_TIMEOUT_SECONDS = 5 * 60

# Lock acquisition timeout: 60 seconds
HIERARCHY_CACHE_LOCK_ACQUIRE_TIMEOUT_SECONDS = 60

MAX_DEPTH = 1000


class HierarchyNodeCacheEntry(BaseModel):
    """Represents a hierarchy node for caching purposes."""

    node_id: int
    parent_id: int | None
    node_type: HierarchyNodeType
    raw_node_id: str

    @classmethod
    def from_db_model(cls, node: "DBHierarchyNode") -> "HierarchyNodeCacheEntry":
        """Create a cache entry from a SQLAlchemy HierarchyNode model."""
        return cls(
            node_id=node.id,
            parent_id=node.parent_id,
            node_type=node.node_type,
            raw_node_id=node.raw_node_id,
        )


def _cache_key(source: DocumentSource) -> str:
    """Get the Redis hash key for hierarchy node cache of a given source.

    This hash stores: node_id -> "parent_id:node_type"
    """
    return f"hierarchy_cache:{source.value}"


def _raw_id_cache_key(source: DocumentSource) -> str:
    """Get the Redis hash key for raw_node_id -> node_id mapping.

    This hash stores: raw_node_id -> node_id
    """
    return f"hierarchy_cache_rawid:{source.value}"


def _source_node_key(source: DocumentSource) -> str:
    """Get the Redis key for the SOURCE-type node ID of a given source.

    This is a simple string key storing the database ID of the SOURCE node.
    """
    return f"hierarchy_source_node:{source.value}"


def _loading_lock_key(source: DocumentSource) -> str:
    """Get the Redis lock key for cache loading of a given source."""
    return f"hierarchy_cache_loading:{source.value}"


def _construct_parent_value(parent_id: int | None, node_type: HierarchyNodeType) -> str:
    """Construct the cached value string from parent_id and node_type.

    Format: "parent_id:node_type" where parent_id is empty string if None.
    """
    parent_str = str(parent_id) if parent_id is not None else ""
    return f"{parent_str}:{node_type.value}"


def _unpack_parent_value(value: str) -> tuple[int | None, HierarchyNodeType | None]:
    """Unpack a cached value string back into (parent_id, node_type).

    Returns None for invalid values.
    """
    parts = value.split(":", 1)
    parent_str = parts[0]
    node_type_str = parts[1] if len(parts) > 1 else ""
    parent_id = int(parent_str) if parent_str else None

    node_type = HierarchyNodeType(node_type_str) if node_type_str else None

    return parent_id, node_type


def cache_hierarchy_node(
    redis_client: Redis,
    source: DocumentSource,
    entry: HierarchyNodeCacheEntry,
) -> None:
    """
    Add or update a single hierarchy node in the Redis cache.

    Called during docfetching when nodes are upserted to Postgres.
    Stores the parent chain mapping, raw_id -> node_id mapping, and
    SOURCE node ID (if this is a SOURCE-type node).

    Args:
        redis_client: Redis client with tenant prefixing
        source: The document source (e.g., CONFLUENCE, GOOGLE_DRIVE)
        entry: The hierarchy node cache entry
    """
    cache_key = _cache_key(source)
    raw_id_key = _raw_id_cache_key(source)

    # Store parent chain: node_id -> "parent_id:node_type"
    value = _construct_parent_value(entry.parent_id, entry.node_type)
    redis_client.hset(cache_key, str(entry.node_id), value)

    # Store raw_id -> node_id mapping
    redis_client.hset(raw_id_key, entry.raw_node_id, str(entry.node_id))

    # If this is the SOURCE node, store its ID in the dedicated key
    if entry.node_type == HierarchyNodeType.SOURCE:
        source_node_key = _source_node_key(source)
        redis_client.set(source_node_key, str(entry.node_id))
        redis_client.expire(source_node_key, HIERARCHY_CACHE_TTL_SECONDS)

    # Refresh TTL on every write (ensures cache stays alive during long indexing)
    redis_client.expire(cache_key, HIERARCHY_CACHE_TTL_SECONDS)
    redis_client.expire(raw_id_key, HIERARCHY_CACHE_TTL_SECONDS)


def cache_hierarchy_nodes_batch(
    redis_client: Redis,
    source: DocumentSource,
    entries: list[HierarchyNodeCacheEntry],
) -> None:
    """
    Add or update multiple hierarchy nodes in the Redis cache.

    Args:
        redis_client: Redis client with tenant prefixing
        source: The document source
        entries: List of HierarchyNodeCacheEntry objects
    """
    if not entries:
        return

    cache_key = _cache_key(source)
    raw_id_key = _raw_id_cache_key(source)
    source_node_key = _source_node_key(source)

    # Build mappings for batch insert
    parent_mapping: dict[str, str] = {}
    raw_id_mapping: dict[str, str] = {}
    source_node_id: int | None = None

    for entry in entries:
        parent_mapping[str(entry.node_id)] = _construct_parent_value(
            entry.parent_id, entry.node_type
        )
        raw_id_mapping[entry.raw_node_id] = str(entry.node_id)

        # Track the SOURCE node if we encounter it
        if entry.node_type == HierarchyNodeType.SOURCE:
            source_node_id = entry.node_id

    # Use hset with mapping for batch insert
    redis_client.hset(cache_key, mapping=parent_mapping)
    redis_client.hset(raw_id_key, mapping=raw_id_mapping)

    # Cache the SOURCE node ID if found
    if source_node_id is not None:
        redis_client.set(source_node_key, str(source_node_id))
        redis_client.expire(source_node_key, HIERARCHY_CACHE_TTL_SECONDS)

    redis_client.expire(cache_key, HIERARCHY_CACHE_TTL_SECONDS)
    redis_client.expire(raw_id_key, HIERARCHY_CACHE_TTL_SECONDS)


def get_node_id_from_raw_id(
    redis_client: Redis,
    source: DocumentSource,
    raw_node_id: str,
) -> tuple[int | None, bool]:
    """
    Get the database node_id for a raw_node_id from the cache.

    Returns:
        Tuple of (node_id or None, found_in_cache)
        - If found_in_cache is False, the raw_id doesn't exist in cache
        - If found_in_cache is True, node_id is the database ID
    """
    raw_id_key = _raw_id_cache_key(source)
    value = redis_client.hget(raw_id_key, raw_node_id)

    if value is None:
        return None, False

    # Decode bytes if needed
    value_str: str
    if isinstance(value, bytes):
        value_str = value.decode("utf-8")
    else:
        value_str = str(value)

    return int(value_str), True


def get_parent_id_from_cache(
    redis_client: Redis,
    source: DocumentSource,
    node_id: int,
) -> tuple[int | None, bool]:
    """
    Get the parent_id for a node from the cache.

    Returns:
        Tuple of (parent_id or None, found_in_cache)
        - If found_in_cache is False, the node doesn't exist in cache
        - If found_in_cache is True, parent_id is the actual parent (or None for root)
    """
    cache_key = _cache_key(source)
    value = redis_client.hget(cache_key, str(node_id))

    if value is None:
        return None, False

    # Decode bytes if needed
    value_str: str
    if isinstance(value, bytes):
        value_str = value.decode("utf-8")
    else:
        value_str = str(value)

    parent_id, _ = _unpack_parent_value(value_str)
    return parent_id, True


def is_cache_populated(redis_client: Redis, source: DocumentSource) -> bool:
    """Check if the cache has any entries for this source."""
    cache_key = _cache_key(source)
    # redis.exists returns int (number of keys that exist)
    exists_result: int = redis_client.exists(cache_key)  # type: ignore[assignment]
    return exists_result > 0


def refresh_hierarchy_cache_from_db(
    redis_client: Redis,
    db_session: Session,
    source: DocumentSource,
) -> None:
    """
    Refresh the entire hierarchy cache for a source from the database.

    This function acquires a distributed lock to ensure only one worker
    performs the refresh. Other workers will wait for the refresh to complete.

    Args:
        redis_client: Redis client with tenant prefixing
        db_session: SQLAlchemy session for database access
        source: The document source to refresh
    """

    lock_key = _loading_lock_key(source)

    # Try to acquire lock - if we can't get it, someone else is refreshing
    lock: RedisLock = redis_client.lock(
        lock_key,
        timeout=HIERARCHY_CACHE_LOCK_TIMEOUT_SECONDS,
        blocking=True,
        blocking_timeout=HIERARCHY_CACHE_LOCK_ACQUIRE_TIMEOUT_SECONDS,
    )

    acquired = lock.acquire(blocking=True)
    if not acquired:
        logger.warning(
            f"Could not acquire lock for hierarchy cache refresh "
            f"for source {source.value} - another worker may be refreshing"
        )
        return

    try:
        # Always refresh from DB when called - new nodes may have been added
        # since the cache was last populated. The lock ensures only one worker
        # does the refresh at a time.
        logger.info(f"Refreshing hierarchy cache for source {source.value} from DB")

        # Load all nodes for this source from DB
        nodes = get_all_hierarchy_nodes_for_source(db_session, source)

        if not nodes:
            logger.warning(f"No hierarchy nodes found in DB for source {source.value}")
            return

        # Batch insert into cache
        cache_entries = [HierarchyNodeCacheEntry.from_db_model(node) for node in nodes]
        cache_hierarchy_nodes_batch(redis_client, source, cache_entries)

        logger.info(
            f"Refreshed hierarchy cache for {source.value} with {len(nodes)} nodes"
        )

    finally:
        try:
            lock.release()
        except Exception as e:
            logger.warning(f"Error releasing hierarchy cache lock: {e}")


def _walk_ancestor_chain(
    redis_client: Redis,
    source: DocumentSource,
    start_node_id: int,
    db_session: Session,
) -> list[int]:
    """
    Walk up the hierarchy tree from a node, collecting all ancestor IDs.

    Internal helper used by both get_ancestors_from_node_id and
    get_ancestors_from_raw_id.
    """
    ancestors: list[int] = []
    current_id: int | None = start_node_id
    visited: set[int] = set()

    while current_id is not None and len(ancestors) < MAX_DEPTH:
        if current_id in visited:
            logger.error(
                f"Cycle detected in hierarchy for source {source.value} "
                f"at node {current_id}. Ancestors so far: {ancestors}"
            )
            break

        visited.add(current_id)
        ancestors.append(current_id)

        parent_id, found = get_parent_id_from_cache(redis_client, source, current_id)

        if not found:
            logger.debug(
                f"Cache miss for hierarchy node {current_id} "
                f"of source {source.value}, attempting refresh"
            )
            refresh_hierarchy_cache_from_db(redis_client, db_session, source)
            parent_id, found = get_parent_id_from_cache(
                redis_client, source, current_id
            )

            if not found:
                logger.error(
                    f"Hierarchy node {current_id} not found in cache "
                    f"for source {source.value} even after refresh."
                )
                break

        current_id = parent_id

    if len(ancestors) >= MAX_DEPTH:
        logger.error(
            f"Hit max depth {MAX_DEPTH} traversing hierarchy for source "
            f"{source.value}. Possible infinite loop or very deep hierarchy."
        )

    return ancestors


def get_ancestors_from_raw_id(
    redis_client: Redis,
    source: DocumentSource,
    parent_hierarchy_raw_node_id: str | None,
    db_session: Session,
) -> list[int]:
    """
    Get all ancestor hierarchy node IDs from a raw_node_id.

    This is the main entry point for getting ancestors from a document's
    parent_hierarchy_raw_node_id. It resolves the raw_id to a database ID
    via Redis cache, then walks up the tree.

    No DB calls are made unless the cache is stale.

    Args:
        redis_client: Redis client with tenant prefixing
        source: The document source
        parent_hierarchy_raw_node_id: The document's parent raw node ID (from connector)
        db_session: DB session for cache refresh if needed

    Returns:
        List of ancestor hierarchy node IDs from parent to root (inclusive).
        Returns list with just SOURCE node ID if parent is None or not found.
    """
    # If no parent specified, return just the SOURCE node
    if parent_hierarchy_raw_node_id is None:
        source_node_id = get_source_node_id_from_cache(redis_client, db_session, source)
        return [source_node_id] if source_node_id else []

    # Resolve raw_id to node_id via Redis
    node_id, found = get_node_id_from_raw_id(
        redis_client, source, parent_hierarchy_raw_node_id
    )

    if not found:
        # Cache miss - try refresh
        logger.debug(
            f"Cache miss for raw_node_id '{parent_hierarchy_raw_node_id}' "
            f"of source {source.value}, attempting refresh"
        )
        refresh_hierarchy_cache_from_db(redis_client, db_session, source)
        node_id, found = get_node_id_from_raw_id(
            redis_client, source, parent_hierarchy_raw_node_id
        )

    if not found or node_id is None:
        logger.error(
            f"Raw node ID '{parent_hierarchy_raw_node_id}' not found in cache "
            f"for source {source.value}. Falling back to SOURCE node only."
        )
        source_node_id = get_source_node_id_from_cache(redis_client, db_session, source)
        return [source_node_id] if source_node_id else []

    # Walk up the ancestor chain
    return _walk_ancestor_chain(redis_client, source, node_id, db_session)


def get_source_node_id_from_cache(
    redis_client: Redis,
    db_session: Session,
    source: DocumentSource,
) -> int | None:
    """
    Get the SOURCE-type node ID for a given source from cache.

    If not in cache and db_session is provided, refreshes from DB.

    Returns:
        The ID of the SOURCE node, or None if not found.
    """
    source_node_key = _source_node_key(source)

    # Try to get from dedicated SOURCE node key
    value = redis_client.get(source_node_key)
    if value is not None:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if not isinstance(value, str):
            raise ValueError(f"SOURCE node value is not a string: {value}")
        return int(value)

    # Not in cache - try refresh from DB
    refresh_hierarchy_cache_from_db(redis_client, db_session, source)

    # Try again after refresh
    value = redis_client.get(source_node_key)
    if value is not None:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if not isinstance(value, str):
            raise ValueError(f"SOURCE node value is not a string: {value}")
        return int(value)

    logger.error(f"SOURCE node not found for source {source.value}")
    return None


def clear_hierarchy_cache(redis_client: Redis, source: DocumentSource) -> None:
    """Clear the hierarchy cache for a source (useful for testing)."""
    cache_key = _cache_key(source)
    raw_id_key = _raw_id_cache_key(source)
    source_node_key = _source_node_key(source)
    redis_client.delete(cache_key)
    redis_client.delete(raw_id_key)
    redis_client.delete(source_node_key)


def ensure_source_node_exists(
    redis_client: Redis,
    db_session: Session,
    source: DocumentSource,
) -> int:
    """
    Ensure that a SOURCE-type hierarchy node exists for the given source and cache it.

    This is the primary entry point for ensuring hierarchy infrastructure is set up
    for a source before processing documents. It should be called early in the
    indexing pipeline (e.g., at the start of docfetching or hierarchy fetching).

    The function:
    1. Checks Redis cache for existing SOURCE node ID
    2. If not cached, ensures the SOURCE node exists in the database
    3. Caches the SOURCE node in Redis for fast subsequent lookups

    This is idempotent and safe to call multiple times concurrently.

    Args:
        redis_client: Redis client with tenant prefixing
        db_session: SQLAlchemy session for database operations
        source: The document source type (e.g., GOOGLE_DRIVE, CONFLUENCE)

    Returns:
        The database ID of the SOURCE-type hierarchy node
    """
    # First check if we already have it cached
    source_node_key = _source_node_key(source)
    cached_value = redis_client.get(source_node_key)

    if cached_value is not None:
        value_str: str
        if isinstance(cached_value, bytes):
            value_str = cached_value.decode("utf-8")
        else:
            value_str = str(cached_value)
        return int(value_str)

    # Not cached - ensure it exists in DB and cache it
    source_node = db_ensure_source_node_exists(db_session, source, commit=True)

    # Cache the SOURCE node
    cache_entry = HierarchyNodeCacheEntry.from_db_model(source_node)
    cache_hierarchy_node(redis_client, source, cache_entry)

    logger.info(
        f"Ensured SOURCE node exists and cached for {source.value}: id={source_node.id}"
    )

    return source_node.id
