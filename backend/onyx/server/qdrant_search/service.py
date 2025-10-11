"""
Service for performing real-time search against Qdrant vector database.
Uses hybrid search (dense + sparse) for optimal results.

Implements prefix caching to accelerate search-as-you-type:
- Pre-computed embeddings for common query prefixes
- Cache hit: ~5-10ms embedding lookup
- Cache miss: ~100-200ms embedding generation
"""

import os
from functools import lru_cache

import cohere
from fastembed import SparseTextEmbedding
from qdrant_client.models import Fusion

from onyx.server.qdrant_search.models import QdrantSearchResponse
from onyx.server.qdrant_search.models import QdrantSearchResult
from onyx.utils.logger import setup_logger
from scratch.qdrant.client import QdrantClient
from scratch.qdrant.prefix_cache.prefix_to_id import prefix_to_id
from scratch.qdrant.schemas.collection_name import CollectionName
from scratch.qdrant.service import QdrantService

logger = setup_logger()


@lru_cache(maxsize=1)
def get_cohere_client() -> cohere.Client:
    """Get cached Cohere client instance."""
    cohere_api_key = os.getenv("COHERE_API_KEY")
    if not cohere_api_key:
        raise ValueError("COHERE_API_KEY environment variable not set")
    return cohere.Client(cohere_api_key)


@lru_cache(maxsize=1)
def get_sparse_embedding_model() -> SparseTextEmbedding:
    """Get cached sparse embedding model instance."""
    # Use BM25 for sparse embeddings
    sparse_model_name = "Qdrant/bm25"
    return SparseTextEmbedding(model_name=sparse_model_name, threads=2)


@lru_cache(maxsize=1)
def get_qdrant_service() -> QdrantService:
    """Get cached Qdrant service instance."""
    client = QdrantClient()
    return QdrantService(client=client)


def search_with_prefix_cache_recommend(
    query: str, qdrant_client: QdrantClient, limit: int = 10
) -> tuple[list, bool]:
    """
    Search using recommend endpoint with prefix cache lookup.

    This uses Qdrant's recommend endpoint with lookup_from parameter to:
    1. Look up the prefix point ID from prefix_cache collection
    2. Use that point's vector to search the main collection
    3. All in a SINGLE API call (no separate retrieve needed!)

    Args:
        query: The search query text
        qdrant_client: Qdrant client instance
        limit: Number of results to return

    Returns:
        Tuple of (results, cache_hit) where cache_hit indicates if cache was used
    """
    try:
        # Normalize query for lookup (lowercase)
        normalized_query = query.lower().strip()

        # Convert prefix to u64 integer point ID
        point_id = prefix_to_id(normalized_query)

        # Use recommend endpoint with lookup_from to search via prefix cache
        # This is THE key optimization from the article!
        from qdrant_client.models import LookupLocation

        results = qdrant_client.client.recommend(
            collection_name=CollectionName.ACCURACY_TESTING,
            positive=[point_id],  # u64 integer point ID from prefix
            limit=limit,
            lookup_from=LookupLocation(
                collection=CollectionName.PREFIX_CACHE
            ),  # Look up vector from cache!
            with_payload=True,
        )

        if results:
            logger.info(
                f"✓ Prefix cache HIT for '{query}' (recommend with lookup_from)"
            )
            return (results, True)
        else:
            logger.info(f"✗ Prefix cache MISS for '{query}' (point not found in cache)")
            return ([], False)

    except Exception as e:
        logger.warning(f"Error using prefix cache recommend: {e}")
        return ([], False)


def embed_query_with_cohere(
    query_text: str,
    cohere_client: cohere.Client,
    model: str = "embed-english-v3.0",
) -> list[float]:
    """
    Embed query text using Cohere API.

    Args:
        query_text: The search query
        cohere_client: Initialized Cohere client
        model: Cohere model name

    Returns:
        Dense embedding vector
    """
    response = cohere_client.embed(
        texts=[query_text],
        model=model,
        input_type="search_query",  # Important: use search_query for queries
    )
    return response.embeddings[0]


def search_documents(query: str, limit: int = 10) -> QdrantSearchResponse:
    """
    Perform hybrid search on Qdrant collection with prefix caching.

    Strategy (from Qdrant article):
    1. Try recommend with lookup_from prefix_cache (cache hit: SINGLE API call!)
    2. If cache miss, generate embeddings and do hybrid search (~100-200ms)

    Args:
        query: Search query text
        limit: Maximum number of results to return

    Returns:
        QdrantSearchResponse with search results
    """
    try:
        logger.info(f"Searching for query: '{query[:50]}'")

        # Get client instances
        qdrant_client = QdrantClient()

        # Try prefix cache with recommend endpoint (article's approach!)
        cache_results, cache_hit = search_with_prefix_cache_recommend(
            query, qdrant_client, limit
        )

        if cache_hit:
            # Cache HIT - use results from recommend (single API call!)
            search_points = cache_results
        else:
            # Cache MISS - fall back to on-the-fly embedding + hybrid search
            logger.info(f"Generating embeddings for query: {query[:50]}...")

            qdrant_service = get_qdrant_service()
            cohere_client = get_cohere_client()
            sparse_model = get_sparse_embedding_model()

            # Generate dense embedding with Cohere
            dense_vector = embed_query_with_cohere(query, cohere_client)

            # Generate sparse embedding
            sparse_embedding = next(sparse_model.query_embed(query))
            from qdrant_client.models import SparseVector

            sparse_vector = SparseVector(
                indices=sparse_embedding.indices.tolist(),
                values=sparse_embedding.values.tolist(),
            )

            # Perform hybrid search
            logger.info("Performing hybrid search...")
            search_results = qdrant_service.hybrid_search(
                dense_query_vector=dense_vector,
                sparse_query_vector=sparse_vector,
                collection_name=CollectionName.ACCURACY_TESTING,
                limit=limit,
                fusion=Fusion.DBSF,  # Distribution-Based Score Fusion
            )
            search_points = search_results.points

        # Convert results to response format (works for both recommend and search)
        results = []
        for point in search_points:
            payload = point.payload or {}
            result = QdrantSearchResult(
                document_id=payload.get("document_id", ""),
                content=payload.get("content", "")[:500],  # Limit content preview
                filename=payload.get("filename"),
                source_type=payload.get("source_type"),
                score=point.score if point.score else 0.0,
                metadata=payload.get("metadata"),
            )
            results.append(result)

        logger.info(f"Found {len(results)} results for query: {query[:50]}")

        return QdrantSearchResponse(
            results=results,
            query=query,
            total_results=len(results),
        )

    except Exception as e:
        logger.error(f"Error searching documents: {e}")
        # Return empty results on error
        return QdrantSearchResponse(
            results=[],
            query=query,
            total_results=0,
        )
