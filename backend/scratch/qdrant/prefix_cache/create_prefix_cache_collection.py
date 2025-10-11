"""
Script to create the prefix_cache collection in Qdrant.

This collection stores pre-computed embeddings for common query prefixes
to accelerate search-as-you-type functionality.
"""

from qdrant_client.models import Distance
from qdrant_client.models import SparseVectorParams
from qdrant_client.models import VectorParams

from scratch.qdrant.client import QdrantClient
from scratch.qdrant.schemas.collection_name import CollectionName


def create_prefix_cache_collection() -> None:
    """
    Create the prefix_cache collection with appropriate vector configurations.

    Collection schema:
    - Dense vectors: 1024 dimensions (Cohere embed-english-v3.0)
    - Sparse vectors: Splade_PP_en_v1
    - Payload: prefix text, hit_count for analytics
    """
    client = QdrantClient()

    collection_name = CollectionName.PREFIX_CACHE

    print(f"Creating collection: {collection_name}")

    # Dense vector config (same as accuracy_testing collection)
    dense_config = VectorParams(
        size=1024,  # Cohere embed-english-v3.0 dimension
        distance=Distance.COSINE,
    )

    # Sparse vector config (same as accuracy_testing collection)
    sparse_config = {"sparse": SparseVectorParams()}

    result = client.create_collection(
        collection_name=collection_name,
        dense_vectors_config={"dense": dense_config},
        sparse_vectors_config=sparse_config,
        shard_number=2,  # Single shard for small cache collection
    )

    if result.success:
        print(f"✓ Collection '{collection_name}' created successfully")

        # Verify collection was created
        collection_info = client.get_collection(collection_name)
        print("\nCollection info:")
        print(f"  Status: {collection_info.status}")
        print(f"  Points: {collection_info.points_count}")
        print(f"  Vectors config: {collection_info.config.params.vectors}")
        print(
            f"  Sparse vectors config: {collection_info.config.params.sparse_vectors}"
        )
    else:
        print(f"✗ Failed to create collection '{collection_name}'")


if __name__ == "__main__":
    create_prefix_cache_collection()
