from uuid import uuid4

from fastembed import SparseTextEmbedding
from fastembed import TextEmbedding
from qdrant_client.models import Distance
from qdrant_client.models import SparseVectorParams
from qdrant_client.models import VectorParams

from .client import QdrantClient
from .performance_testing.fake_chunk_helpers import fake_acl
from .performance_testing.fake_chunk_helpers import fake_source_type
from .performance_testing.fake_chunk_helpers import generate_fake_qdrant_chunks
from .schemas.chunk import QdrantChunk
from .schemas.collection_name import CollectionName
from .service import QdrantService


def main():
    collection_name = CollectionName.TEST_COLLECTION
    dense_model_name = "nomic-ai/nomic-embed-text-v1"
    sparse_model_name = "prithivida/Splade_PP_en_v1"

    # Initialize client and service
    dense_embedding_model = TextEmbedding(model_name=dense_model_name)
    sparse_embedding_model = SparseTextEmbedding(model_name=sparse_model_name)
    service = QdrantService(client=QdrantClient())

    # Get embedding size for dense vectors
    dense_embedding_size = service.client.get_embedding_size(dense_model_name)

    # Delete and recreate collection
    service.client.delete_collection(collection_name=collection_name)
    service.client.create_collection(
        collection_name=collection_name,
        dense_vectors_config={
            "dense": VectorParams(size=dense_embedding_size, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(),
        },
    )
    print(f"Collection {collection_name} created")

    # Generate fake chunks
    num_fake_chunks = 100
    print(f"Generating {num_fake_chunks} fake chunks...")
    fake_chunks = list(generate_fake_qdrant_chunks(num_fake_chunks))
    print(f"Generated {len(fake_chunks)} chunks")

    # Write to Qdrant using service
    print("Writing chunks to Qdrant...")
    import time

    start_time = time.time()
    result = service.embed_and_upsert_chunks(
        fake_chunks, dense_embedding_model, sparse_embedding_model, collection_name
    )
    elapsed_time = time.time() - start_time
    print(f"Upsert result: {result}")
    print(f"Time taken: {elapsed_time:.2f} seconds")

    # Manually insert a specific chunk for testing
    manual_doc_id = uuid4()
    manual_content = "China is a very large nation"
    manual_acl = fake_acl()
    manual_source_type = fake_source_type()
    chunk_id = uuid4()
    print("\nManually inserting a chunk with the following details:")
    print(f"Chunk ID: {chunk_id}")
    print(f"Document ID: {manual_doc_id}")
    print(f"Content: {manual_content}")
    print(f"ACL: {manual_acl}")
    print(f"Source Type: {manual_source_type}")

    manual_result = service.embed_and_upsert_chunks(
        [
            QdrantChunk(
                id=chunk_id,
                document_id=manual_doc_id,
                source_type=manual_source_type,
                access_control_list=manual_acl,
                content=manual_content,
            )
        ],
        dense_embedding_model,
        sparse_embedding_model,
        collection_name,
    )
    print(f"Upsert result: {manual_result}")

    # Test hybrid search using service
    query = "What is the biggest nation?"
    print(f"\nTesting hybrid search (RRF fusion)... with query: '{query}'")

    # Generate query embeddings
    dense_query_vector, sparse_query_vector = service.generate_query_embeddings(
        query, dense_embedding_model, sparse_embedding_model
    )

    # Perform search with pre-computed embeddings
    search_result = service.hybrid_search(
        dense_query_vector=dense_query_vector,
        sparse_query_vector=sparse_query_vector,
        collection_name=collection_name,
        limit=3,
    )

    print(f"\nSearch Results for '{query}':")
    print(f"Found {len(search_result.points)} results\n")
    for idx, point in enumerate(search_result.points, 1):
        print(f"{idx}. Score: {point.score:.4f}")
        print(f"   ID: {point.id}")
        print(f"   Document ID: {point.payload.get('document_id')}")
        print(f"   Source: {point.payload.get('source_type')}")
        print(f"   ACL: {point.payload.get('access_control_list')}")
        print(f"   Content: {point.payload.get('content')}")
        print()


if __name__ == "__main__":
    main()
