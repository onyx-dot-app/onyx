"""Cache manager for storing and retrieving prompt cache metadata."""

import hashlib
import json
from datetime import datetime
from datetime import timezone

from onyx.configs.model_configs import PROMPT_CACHE_REDIS_TTL_MULTIPLIER
from onyx.key_value_store.store import PgRedisKVStore
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.utils import normalize_language_model_input
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

REDIS_KEY_PREFIX = "prompt_cache:"
# Cache TTL multiplier - store caches slightly longer than provider TTL
# This allows for some clock skew and ensures we don't lose cache metadata prematurely
# Value is configurable via PROMPT_CACHE_REDIS_TTL_MULTIPLIER env var (default: 1.2)
CACHE_TTL_MULTIPLIER = PROMPT_CACHE_REDIS_TTL_MULTIPLIER


class CacheManager:
    """Manages storage and retrieval of prompt cache metadata."""

    def __init__(self, kv_store: PgRedisKVStore | None = None) -> None:
        """Initialize the cache manager.

        Args:
            kv_store: Optional key-value store. If None, creates a new PgRedisKVStore.
        """
        self._kv_store = kv_store or PgRedisKVStore()

    def _build_cache_key(
        self,
        provider: str,
        model_name: str,
        cache_key_hash: str,
        tenant_id: str | None = None,
    ) -> str:
        """Build a Redis/PostgreSQL key for cache metadata.

        Args:
            provider: LLM provider name (e.g., "openai", "anthropic")
            model_name: Model name
            cache_key_hash: Hash of the cacheable prefix content
            tenant_id: Tenant ID. If None, uses current tenant from context.

        Returns:
            Cache key string
        """
        if tenant_id is None:
            tenant_id = get_current_tenant_id()
        return f"{REDIS_KEY_PREFIX}{tenant_id}:{provider}:{model_name}:{cache_key_hash}"

    def store_cache_metadata(
        self,
        metadata: CacheMetadata,
    ) -> None:
        """Store cache metadata.

        Args:
            metadata: Cache metadata to store
            ttl_seconds: Optional TTL in seconds. If None, uses provider default.
        """
        try:
            cache_key = self._build_cache_key(
                metadata.provider,
                metadata.model_name,
                metadata.cache_key,
                metadata.tenant_id,
            )

            # Update last_accessed timestamp
            metadata.last_accessed = datetime.now(timezone.utc)

            # Serialize metadata
            metadata_dict = metadata.model_dump(mode="json")

            # Store in key-value store
            # Note: PgRedisKVStore doesn't support TTL directly, but Redis will
            # handle expiration. For PostgreSQL persistence, we rely on cleanup
            # based on last_accessed timestamp.
            self._kv_store.store(cache_key, metadata_dict, encrypt=False)

            logger.debug(
                f"Stored cache metadata: provider={metadata.provider}, "
                f"model={metadata.model_name}, cache_key={metadata.cache_key[:16]}..., "
                f"tenant_id={metadata.tenant_id}"
            )
        except Exception as e:
            # Best-effort: log and continue
            logger.warning(f"Failed to store cache metadata: {str(e)}")

    def retrieve_cache_metadata(
        self,
        provider: str,
        model_name: str,
        cache_key_hash: str,
        tenant_id: str | None = None,
    ) -> CacheMetadata | None:
        """Retrieve cache metadata.

        Args:
            provider: LLM provider name
            model_name: Model name
            cache_key_hash: Hash of the cacheable prefix content
            tenant_id: Tenant ID. If None, uses current tenant from context.

        Returns:
            CacheMetadata if found, None otherwise
        """
        try:
            cache_key = self._build_cache_key(
                provider, model_name, cache_key_hash, tenant_id
            )
            metadata_dict = self._kv_store.load(cache_key, refresh_cache=False)

            # Deserialize metadata
            metadata = CacheMetadata.model_validate(metadata_dict)

            # Update last_accessed timestamp
            metadata.last_accessed = datetime.now(timezone.utc)
            self.store_cache_metadata(metadata)

            logger.debug(
                f"Retrieved cache metadata: provider={provider}, "
                f"model={model_name}, cache_key={cache_key_hash[:16]}..., "
                f"tenant_id={tenant_id}"
            )
            return metadata
        except Exception as e:
            # Best-effort: log and continue
            logger.debug(f"Cache metadata not found or error retrieving: {str(e)}")
            return None

    def delete_cache_metadata(
        self,
        provider: str,
        model_name: str,
        cache_key_hash: str,
        tenant_id: str | None = None,
    ) -> None:
        """Delete cache metadata.

        Args:
            provider: LLM provider name
            model_name: Model name
            cache_key_hash: Hash of the cacheable prefix content
            tenant_id: Tenant ID. If None, uses current tenant from context.
        """
        try:
            cache_key = self._build_cache_key(
                provider, model_name, cache_key_hash, tenant_id
            )
            self._kv_store.delete(cache_key)
            logger.debug(
                f"Deleted cache metadata for provider={provider}, "
                f"model={model_name}, cache_key={cache_key_hash[:16]}..."
            )
        except Exception as e:
            # Best-effort: log and continue
            logger.warning(f"Failed to delete cache metadata: {str(e)}")


def _make_json_serializable(obj: object) -> object:
    """Recursively convert objects to JSON-serializable types.

    Handles Pydantic models, dicts, lists, and other common types.
    """
    if hasattr(obj, "model_dump"):
        # Pydantic v2 model
        return obj.model_dump(mode="json")
    elif hasattr(obj, "dict"):
        # Pydantic v1 model or similar
        return _make_json_serializable(obj.dict())
    elif isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        # Fallback: convert to string representation
        return str(obj)


def generate_cache_key_hash(
    cacheable_prefix: LanguageModelInput,
    provider: str,
    model_name: str,
    tenant_id: str,
) -> str:
    """Generate a deterministic cache key hash from cacheable prefix.

    Args:
        cacheable_prefix: LanguageModelInput (str or Sequence[ChatCompletionMessage])
        provider: LLM provider name
        model_name: Model name
        tenant_id: Tenant ID

    Returns:
        SHA256 hash as hex string
    """
    # Normalize to Sequence[ChatCompletionMessage] for consistent hashing
    messages = normalize_language_model_input(cacheable_prefix)
    # Convert to list of dicts for serialization, handling nested Pydantic models
    messages_dict = [_make_json_serializable(dict(msg)) for msg in messages]

    # Serialize messages in a deterministic way
    # Include only content, roles, and order - exclude timestamps or dynamic fields
    serialized = json.dumps(
        {
            "messages": messages_dict,
            "provider": provider,
            "model": model_name,
            "tenant_id": tenant_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
