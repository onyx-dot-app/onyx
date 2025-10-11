"""
Schema for prefix cache entries.

The prefix cache stores pre-computed embeddings for common query prefixes
to accelerate search-as-you-type functionality.
"""

from pydantic import BaseModel


class PrefixCacheEntry(BaseModel):
    """
    Represents a cached query prefix with its pre-computed embeddings.

    Attributes:
        prefix: The query prefix text (e.g., "doc", "docker", "kubernetes")
        dense_embedding: Pre-computed dense vector embedding
        sparse_indices: Pre-computed sparse vector indices
        sparse_values: Pre-computed sparse vector values
        hit_count: Number of times this prefix has been used (for analytics)
    """

    prefix: str
    dense_embedding: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
    hit_count: int = 0
