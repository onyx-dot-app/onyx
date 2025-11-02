"""
Script to generate and insert 1 million chunks into Qdrant for load testing.
Uses fake embeddings for speed.
"""

import time

from qdrant_client.models import Distance
from qdrant_client.models import OptimizersConfigDiff
from qdrant_client.models import SparseVectorParams
from qdrant_client.models import VectorParams

from ..client import QdrantClient
from ..schemas.collection_name import CollectionName
from ..service import QdrantService
from .fake_chunk_helpers import generate_fake_embeddings_for_chunks
from .fake_chunk_helpers import generate_fake_qdrant_chunks


def main():
    collection_name = CollectionName.TEST_COLLECTION
    vector_size = 768  # nomic-embed-text-v1 dimension
    sparse_dims = 100  # typical sparse vector size

    # Control whether to index while uploading
    index_while_uploading = False

    # Initialize client and service
    service = QdrantService(client=QdrantClient())

    # Use the vector size directly (no need to query embedding model)
    dense_embedding_size = vector_size

    # Delete and recreate collection
    print(f"Setting up collection: {collection_name}")
    print(f"Index while uploading: {index_while_uploading}")
    service.client.delete_collection(collection_name=collection_name)

    # Set indexing threshold based on mode
    optimizer_config = (
        None if index_while_uploading else OptimizersConfigDiff(indexing_threshold=0)
    )

    service.client.create_collection(
        collection_name=collection_name,
        dense_vectors_config={
            "dense": VectorParams(size=dense_embedding_size, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(),
        },
        optimizers_config=optimizer_config,
        shard_number=4,
    )
    print(f"Collection {collection_name} created")
    print(f"Optimizer config: {optimizer_config}\n")

    # Generate and insert chunks in batches
    total_chunks = 1_000_000
    batch_size = 1_854
    num_batches = total_chunks // batch_size

    print(
        f"Generating and inserting {total_chunks:,} chunks in {num_batches} batches of {batch_size:,}..."
    )
    print()

    overall_start = time.time()

    for batch_num in range(num_batches):
        print(f"=== Batch {batch_num + 1}/{num_batches} ===")

        # Step 1: Generate chunks
        gen_start = time.time()
        fake_chunks = list(generate_fake_qdrant_chunks(batch_size))
        gen_time = time.time() - gen_start
        print(f"1. Generate chunks: {gen_time:.2f}s")

        # Step 2: Generate fake embeddings
        emb_start = time.time()
        dense_embeddings, sparse_embeddings = generate_fake_embeddings_for_chunks(
            fake_chunks, vector_size, sparse_dims
        )
        emb_time = time.time() - emb_start
        print(f"2. Generate embeddings: {emb_time:.2f}s")

        # Step 3: Build points
        build_start = time.time()
        points = service.build_points_from_chunks_and_embeddings(
            fake_chunks, dense_embeddings, sparse_embeddings
        )
        build_time = time.time() - build_start
        print(f"3. Build points: {build_time:.2f}s")

        # Step 4: Insert to Qdrant (likely bottleneck)
        insert_start = time.time()
        result = service.client.override_points(points, collection_name)
        insert_time = time.time() - insert_start
        print(f"4. Insert to Qdrant: {insert_time:.2f}s")

        batch_total = time.time() - gen_start
        chunks_processed = (batch_num + 1) * batch_size

        print(f"Batch total: {batch_total:.2f}s")
        print(f"Status: {result.status}")
        print(f"Chunks processed: {chunks_processed:,} / {total_chunks:,}")
        print()

    total_elapsed = time.time() - overall_start

    print("=" * 60)
    print("COMPLETE")
    print("=" * 60)
    print(f"Total chunks inserted: {total_chunks:,}")
    print(f"Total time: {total_elapsed:.2f} seconds ({total_elapsed / 60:.1f} minutes)")
    print(f"Average rate: {total_chunks / total_elapsed:.1f} chunks/sec")
    print()

    print("Collection info:")
    collection_info = service.client.get_collection(collection_name)
    print(f"  Points count: {collection_info.points_count:,}")
    print(f"  Indexed vectors count: {collection_info.indexed_vectors_count:,}")
    print(f"  Optimizer status: {collection_info.optimizer_status}")
    print(f"  Status: {collection_info.status}")

    # Only need to trigger indexing if we disabled it during upload
    if not index_while_uploading:
        print("\nTriggering indexing (was disabled during upload)...")

        service.client.update_collection(
            collection_name=collection_name,
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=20000,
            ),
        )
        print("Collection optimizers config updated - indexing will now proceed")
    else:
        print("\nIndexing was enabled during upload - no manual trigger needed")

    fresh_collection_info = service.client.get_collection(collection_name)
    print(f"  Points count: {fresh_collection_info.points_count:,}")
    print(f"  Indexed vectors count: {fresh_collection_info.indexed_vectors_count:,}")
    print(f"  Optimizer status: {fresh_collection_info.optimizer_status}")
    print(f"  Status: {fresh_collection_info.status}")


if __name__ == "__main__":
    main()
