"""Cache manager for storing and retrieving prompt cache metadata."""

import hashlib
import json

from onyx.llm.interfaces import LanguageModelInput
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _make_json_serializable(obj: object) -> object:
    """Recursively convert objects to JSON-serializable types.

    Handles Pydantic models, dicts, lists, and other common types.
    """
    if hasattr(obj, "model_dump"):
        # Pydantic v2 model
        return obj.model_dump(mode="json")  # ty: ignore[call-non-callable]
    elif hasattr(obj, "dict"):
        # Pydantic v1 model or similar
        return _make_json_serializable(obj.dict())  # ty: ignore[call-non-callable]
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
        cacheable_prefix: Single message or list of messages to hash
        provider: LLM provider name
        model_name: Model name
        tenant_id: Tenant ID

    Returns:
        SHA256 hash as hex string
    """
    # Normalize to list for consistent hashing; _make_json_serializable handles Pydantic models
    messages = (
        cacheable_prefix if isinstance(cacheable_prefix, list) else [cacheable_prefix]
    )
    messages_dict = [_make_json_serializable(msg) for msg in messages]

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
