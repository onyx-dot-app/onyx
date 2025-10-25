"""
Benchmark script for testing ACL filtering performance in Qdrant.
Inserts many chunks with the same ACL, then measures latency of filtering by that ACL.
"""

import time

from fastembed import SparseTextEmbedding
from fastembed import TextEmbedding
from qdrant_client.models import DatetimeRange
from qdrant_client.models import FieldCondition
from qdrant_client.models import Filter
from qdrant_client.models import HasIdCondition
from qdrant_client.models import MatchValue

from ..client import QdrantClient
from ..schemas.collection_name import CollectionName
from ..schemas.source_type import SourceType
from ..service import QdrantService
from .fake_chunk_helpers import get_email_pool


def main():
    collection_name = CollectionName.TEST_COLLECTION
    dense_model_name = "nomic-ai/nomic-embed-text-v1"
    sparse_model_name = "Qdrant/bm25"
    # sparse_model_name = "prithivida/Splade_PP_en_v1"

    # Initialize client and service
    dense_embedding_model = TextEmbedding(model_name=dense_model_name)
    sparse_embedding_model = SparseTextEmbedding(model_name=sparse_model_name)
    service = QdrantService(client=QdrantClient())

    collection_info = service.client.get_collection(collection_name=collection_name)
    print(f"\nCollection {collection_name} info:")
    print(f"  Status: {collection_info.status}")
    print(f"  Points count: {collection_info.points_count:,}")
    print(f"  Indexed vectors count: {collection_info.indexed_vectors_count:,}")
    print(f"  Optimizer status: {collection_info.optimizer_status}")
    print(f"  Payload schema: {collection_info.payload_schema}")
    print()

    source_type_filter = Filter(
        should=[
            FieldCondition(
                key="source_type", match=MatchValue(value=SourceType.GITHUB)
            ),
            FieldCondition(key="source_type", match=MatchValue(value=SourceType.ASANA)),
            FieldCondition(key="source_type", match=MatchValue(value=SourceType.BOX)),
        ]
    )

    query_text = (
        "this is the same content for all chunks to test filtering performance."
    )

    # Pre-compute query embeddings (exclude from search timing)
    print("\nGenerating query embeddings...")
    emb_start = time.time()
    dense_query_vector, sparse_query_vector = service.generate_query_embeddings(
        query_text, dense_embedding_model, sparse_embedding_model
    )
    emb_time = time.time() - emb_start
    print(f"Embedding time: {emb_time * 1000:.2f}ms")

    # Test different limits
    test_limits = [1, 10, 100, 1000, 10000]

    # Baseline: No filters
    print("\n" + "=" * 60)
    print("BENCHMARK: No Filters (Baseline)")
    print("=" * 60)
    print("Filter: None")
    print(f"{'Limit':<10} {'Results':<10} {'Latency (ms)':<15}")
    print("-" * 60)

    for test_limit in test_limits:
        start = time.time()

        search_result = service.hybrid_search(
            dense_query_vector=dense_query_vector,
            sparse_query_vector=sparse_query_vector,
            collection_name=collection_name,
            limit=test_limit,
            query_filter=None,  # No filter
        )

        latency = time.time() - start

        print(
            f"{test_limit:<10} {len(search_result.points):<10} {latency * 1000:<15.2f}"
        )

    print("=" * 60)

    print("\n" + "=" * 60)
    print("BENCHMARK: Source Type Filter (One-to-Many)")
    print("=" * 60)
    print("Filter: source_type in (github, asana, box)")
    print(f"{'Limit':<10} {'Results':<10} {'Latency (ms)':<15}")
    print("-" * 60)

    for test_limit in test_limits:
        # Measure ONLY search latency (no embedding overhead)
        start = time.time()

        search_result = service.hybrid_search(
            dense_query_vector=dense_query_vector,
            sparse_query_vector=sparse_query_vector,
            collection_name=collection_name,
            limit=test_limit,
            query_filter=source_type_filter,
        )

        latency = time.time() - start

        print(
            f"{test_limit:<10} {len(search_result.points):<10} {latency * 1000:<15.2f}"
        )

    print("=" * 60)

    # Test ACL filtering (many-to-many relationship)
    print("\n" + "=" * 60)
    print("BENCHMARK: ACL Filtering (Many-to-Many)")
    print("=" * 60)

    # Pick a known email from the pool
    test_email = get_email_pool()[0]  # "user_000@example.com"

    # Create ACL filter
    acl_filter = Filter(
        must=[
            FieldCondition(
                key="access_control_list", match=MatchValue(value=test_email)
            )
        ]
    )

    print(f"Filter: access_control_list contains '{test_email}'")
    print(f"{'Limit':<10} {'Results':<10} {'Latency (ms)':<15}")
    print("-" * 60)

    for test_limit in test_limits:
        start = time.time()

        search_result = service.hybrid_search(
            dense_query_vector=dense_query_vector,
            sparse_query_vector=sparse_query_vector,
            collection_name=collection_name,
            limit=test_limit,
            query_filter=acl_filter,
        )

        latency = time.time() - start

        print(
            f"{test_limit:<10} {len(search_result.points):<10} {latency * 1000:<15.2f}"
        )

    print("=" * 60)

    # Test composite filtering (source_type AND created_at)
    print("\n" + "=" * 60)
    print("BENCHMARK: Composite Filter (Source + Time Range)")
    print("=" * 60)

    import datetime

    # Filter for source_type=ASANA AND created_at within last 30 days
    thirty_days_ago = datetime.datetime.now() - datetime.timedelta(days=30)

    composite_filter = Filter(
        must=[
            FieldCondition(key="source_type", match=MatchValue(value=SourceType.ASANA)),
            FieldCondition(
                key="created_at", range=DatetimeRange(gte=thirty_days_ago.isoformat())
            ),
        ]
    )

    print(f"Filter: source_type = ASANA AND created_at >= {thirty_days_ago.date()}")
    print(f"{'Limit':<10} {'Results':<10} {'Latency (ms)':<15}")
    print("-" * 60)

    for test_limit in test_limits:
        start = time.time()

        search_result = service.hybrid_search(
            dense_query_vector=dense_query_vector,
            sparse_query_vector=sparse_query_vector,
            collection_name=collection_name,
            limit=test_limit,
            query_filter=composite_filter,
        )

        latency = time.time() - start

        print(
            f"{test_limit:<10} {len(search_result.points):<10} {latency * 1000:<15.2f}"
        )

    print("=" * 60)

    # Test filtering by 200 chunk IDs
    print("\n" + "=" * 60)
    print("BENCHMARK: Filter by 200 Chunk IDs")
    print("=" * 60)

    # First, get 200 chunk IDs from the collection
    print("Fetching 200 chunk IDs from collection...")
    sample_search = service.hybrid_search(
        dense_query_vector=dense_query_vector,
        sparse_query_vector=sparse_query_vector,
        collection_name=collection_name,
        limit=200,
        query_filter=None,
    )

    chunk_ids = [point.id for point in sample_search.points]
    print(f"Retrieved {len(chunk_ids)} chunk IDs")

    # Create filter with all 200 IDs
    id_filter = Filter(must=[HasIdCondition(has_id=chunk_ids)])

    print(f"Filter: chunk_id IN ({len(chunk_ids)} IDs)")
    print(f"{'Limit':<10} {'Results':<10} {'Latency (ms)':<15}")
    print("-" * 60)

    for test_limit in test_limits:
        start = time.time()

        search_result = service.hybrid_search(
            dense_query_vector=dense_query_vector,
            sparse_query_vector=sparse_query_vector,
            collection_name=collection_name,
            limit=test_limit,
            query_filter=id_filter,
        )

        latency = time.time() - start

        print(
            f"{test_limit:<10} {len(search_result.points):<10} {latency * 1000:<15.2f}"
        )

    print("=" * 60)

    # Test concurrent queries
    print("\n" + "=" * 60)
    print("BENCHMARK: Concurrent Queries (50 parallel)")
    print("=" * 60)

    import concurrent.futures

    # Use the source_type filter from the first test
    num_concurrent = 50
    query_limit = 100

    print(f"Running {num_concurrent} concurrent queries with limit={query_limit}")
    print("Filter: source_type in (github, asana, box)")

    def run_single_search():
        """Helper function to run a single search."""
        return service.hybrid_search(
            dense_query_vector=dense_query_vector,
            sparse_query_vector=sparse_query_vector,
            collection_name=collection_name,
            limit=query_limit,
            query_filter=source_type_filter,
        )

    # Execute concurrent searches
    start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_concurrent) as executor:
        futures = [executor.submit(run_single_search) for _ in range(num_concurrent)]
        results = [
            future.result() for future in concurrent.futures.as_completed(futures)
        ]

    total_latency = time.time() - start

    print("\nResults:")
    print(f"  Total queries: {num_concurrent}")
    print(f"  Total time: {total_latency * 1000:.2f}ms ({total_latency:.2f}s)")
    print(
        f"  Average latency per query: {(total_latency / num_concurrent) * 1000:.2f}ms"
    )
    print(f"  Queries per second: {num_concurrent / total_latency:.2f}")
    print(f"  All queries returned results: {all(len(r.points) > 0 for r in results)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
