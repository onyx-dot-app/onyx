"""Interfaces and data structures for prompt caching."""

from datetime import datetime

from pydantic import BaseModel


class CacheMetadata(BaseModel):
    """Metadata for cached prompt prefixes."""

    cache_key: str
    provider: str
    model_name: str
    tenant_id: str
    created_at: datetime
    last_accessed: datetime
    # Provider-specific metadata
    # TODO: Add explicit caching support in future PR
    # vertex_block_numbers: dict[str, str] | None = None  # message_hash -> block_number
    # anthropic_cache_id: str | None = None
