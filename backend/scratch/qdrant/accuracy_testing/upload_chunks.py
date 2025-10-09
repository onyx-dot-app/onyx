"""
Script to upload documents from target_docs.jsonl to Qdrant for accuracy testing.
Converts target documents to QdrantChunk format and embeds them using real embedding models.

Performance optimizations:
- Medium batch sizes (50 documents per batch) to balance speed and memory
- Controlled threading (2 threads) for stability
- Parallel embedding (dense and sparse run concurrently)
- Aggressive garbage collection to prevent OOM
"""

import datetime
import gc
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import cohere
from dotenv import load_dotenv
from fastembed import SparseTextEmbedding
from qdrant_client.models import Distance
from qdrant_client.models import OptimizersConfigDiff
from qdrant_client.models import SparseVector
from qdrant_client.models import SparseVectorParams
from qdrant_client.models import VectorParams

from scratch.qdrant.accuracy_testing.target_document_schema import TargetDocument
from scratch.qdrant.client import QdrantClient
from scratch.qdrant.schemas.chunk import QdrantChunk
from scratch.qdrant.schemas.collection_name import CollectionName
from scratch.qdrant.schemas.embeddings import ChunkDenseEmbedding
from scratch.qdrant.schemas.embeddings import ChunkSparseEmbedding


def load_target_documents(jsonl_path: Path) -> list[TargetDocument]:
    """Load target documents from JSONL file."""
    documents = []
    with open(jsonl_path, "r") as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                documents.append(TargetDocument(**data))
    return documents


def embed_with_cohere(
    texts: list[str],
    cohere_client: cohere.Client,
    model: str = "embed-english-v3.0",
    input_type: str = "search_document",
    batch_size: int = 96,  # Cohere's max batch size is 96
    max_retries: int = 5,
) -> list[list[float]]:
    """
    Embed texts using Cohere API with batching support and retry logic.

    Cohere API processes batches internally in parallel, so we just need to
    send the full batch and it will be handled efficiently.

    Args:
        texts: List of texts to embed
        cohere_client: Initialized Cohere client
        model: Cohere model name
        input_type: Type of input - "search_document" for documents, "search_query" for queries
        batch_size: Maximum batch size for Cohere API (default 96)
        max_retries: Maximum number of retries for transient errors

    Returns:
        List of embedding vectors
    """

    def embed_batch_with_retry(batch_texts: list[str]) -> list[list[float]]:
        """Embed a single batch with exponential backoff retry."""
        for attempt in range(max_retries):
            try:
                response = cohere_client.embed(
                    texts=batch_texts,
                    model=model,
                    input_type=input_type,
                )
                return response.embeddings
            except Exception as e:
                if attempt == max_retries - 1:
                    # Last attempt failed, re-raise
                    raise

                # Calculate backoff time: 2^attempt seconds (1s, 2s, 4s, 8s, 16s)
                backoff_time = 2**attempt
                print(
                    f"   ⚠️  Error embedding batch (attempt {attempt + 1}/{max_retries}): {str(e)[:100]}"
                )
                print(f"   ⏳ Retrying in {backoff_time}s...")
                time.sleep(backoff_time)

        # Should never reach here, but just in case
        raise Exception("Max retries exceeded")

    # If texts fit in one batch, send directly
    if len(texts) <= batch_size:
        return embed_batch_with_retry(texts)

    # Otherwise, split into multiple batches and process
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        batch_embeddings = embed_batch_with_retry(batch_texts)
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


def chunks_to_cohere_embeddings(
    chunks: list[QdrantChunk],
    cohere_client: cohere.Client,
    model: str = "embed-english-v3.0",
) -> list[ChunkDenseEmbedding]:
    """
    Convert QdrantChunks to embeddings using Cohere.

    Args:
        chunks: List of chunks to embed
        cohere_client: Initialized Cohere client
        model: Cohere model name

    Returns:
        List of ChunkDenseEmbedding objects
    """
    texts = [chunk.content for chunk in chunks]
    embeddings = embed_with_cohere(
        texts, cohere_client, model, input_type="search_document"
    )

    return [
        ChunkDenseEmbedding(chunk_id=chunk.id, vector=embedding)
        for chunk, embedding in zip(chunks, embeddings)
    ]


def chunks_to_bm25_embeddings(
    chunks: list[QdrantChunk],
    sparse_embedding_model: SparseTextEmbedding,
) -> list[ChunkSparseEmbedding]:
    """
    Convert QdrantChunks to BM25 sparse embeddings.

    Args:
        chunks: List of chunks to embed
        sparse_embedding_model: Initialized BM25 model

    Returns:
        List of ChunkSparseEmbedding objects
    """
    sparse_vectors = sparse_embedding_model.passage_embed(
        [chunk.content for chunk in chunks]
    )
    return [
        ChunkSparseEmbedding(
            chunk_id=chunk.id,
            vector=SparseVector(
                indices=vector.indices.tolist(), values=vector.values.tolist()
            ),
        )
        for chunk, vector in zip(chunks, sparse_vectors)
    ]


def convert_target_doc_to_chunks(
    target_doc: TargetDocument, max_chunk_length: int = 8000
) -> list[QdrantChunk]:
    """
    Convert a TargetDocument to one or more QdrantChunks.

    - Splits long documents into multiple chunks if needed
    - Each chunk gets a unique UUID
    - All chunks share the same document_id for traceability
    - Uses filename if available, otherwise falls back to document_id
    - Uses empty ACL (public access)
    - Uses current time for created_at

    Args:
        target_doc: The document to convert
        max_chunk_length: Maximum characters per chunk (default 8000 = ~2000 tokens)

    Returns:
        List of QdrantChunk objects (1 or more)
    """
    created_at = datetime.datetime.now()
    content = target_doc.content
    title = target_doc.title

    # Prepend title to content if title is not None
    if title is not None:
        content = f"{title}\n{content}"

    # If content fits in one chunk, return single chunk
    if len(content) <= max_chunk_length:
        return [
            QdrantChunk(
                id=uuid4(),
                document_id=target_doc.document_id,
                filename=target_doc.filename,
                source_type=None,
                access_control_list=None,
                created_at=created_at,
                content=content,
            )
        ]

    # Split content into multiple chunks
    chunks = []
    num_chunks = (len(content) + max_chunk_length - 1) // max_chunk_length

    for i in range(num_chunks):
        start_idx = i * max_chunk_length
        end_idx = min(start_idx + max_chunk_length, len(content))
        chunk_content = content[start_idx:end_idx]

        chunks.append(
            QdrantChunk(
                id=uuid4(),
                document_id=target_doc.document_id,
                filename=target_doc.filename,
                source_type=None,
                access_control_list=None,
                created_at=created_at,
                content=chunk_content,
            )
        )

    return chunks


def main():
    collection_name = CollectionName.ACCURACY_TESTING

    # Embedding model configuration
    cohere_model = "embed-english-v3.0"
    sparse_model_name = "Qdrant/bm25"
    vector_size = 1024  # embed-english-v3.0 dimension

    # Control whether to index while uploading
    index_while_uploading = False

    # Batch processing configuration
    # Cohere API can handle up to 96 texts per request and processes them in parallel
    batch_size = 96  # Match Cohere's max batch size for optimal performance

    # Load environment variables from .env file
    env_path = Path(__file__).parent.parent.parent.parent.parent / ".vscode" / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment variables from {env_path}")
    else:
        print(f"Warning: .env file not found at {env_path}")

    # Initialize Cohere client
    print("Initializing Cohere client...")
    cohere_api_key = os.getenv("COHERE_API_KEY")
    if not cohere_api_key:
        raise ValueError("COHERE_API_KEY environment variable not set")

    cohere_client = cohere.Client(cohere_api_key)
    print(f"Cohere client initialized with model: {cohere_model}")

    # Initialize BM25 sparse embedding model
    print("Initializing BM25 sparse embedding model...")
    sparse_embedding_model = SparseTextEmbedding(
        model_name=sparse_model_name, threads=2
    )
    print("BM25 model initialized\n")

    # Initialize Qdrant client
    qdrant_client = QdrantClient()

    # Delete and recreate collection
    print(f"Setting up collection: {collection_name}")
    print(f"Index while uploading: {index_while_uploading}")
    qdrant_client.delete_collection(collection_name=collection_name)

    # Set indexing threshold based on mode
    optimizer_config = (
        None if index_while_uploading else OptimizersConfigDiff(indexing_threshold=0)
    )

    # Create collection with both dense (Cohere) and sparse (BM25) vectors
    qdrant_client.create_collection(
        collection_name=collection_name,
        dense_vectors_config={
            "dense": VectorParams(size=vector_size, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(),
        },
        optimizers_config=optimizer_config,
        shard_number=4,
    )
    print(f"Collection {collection_name} created")
    print(f"Optimizer config: {optimizer_config}\n")

    # Load target documents - stream them to count total first
    jsonl_path = Path(__file__).parent / "target_docs.jsonl"
    print(f"Counting documents in {jsonl_path}...")
    with open(jsonl_path, "r") as f:
        total_docs = sum(1 for line in f if line.strip())
    print(f"Found {total_docs:,} documents\n")

    # Process in batches - stream documents and process in chunks
    num_batches = (total_docs + batch_size - 1) // batch_size
    print(
        f"Processing {total_docs:,} chunks in {num_batches} batches of {batch_size:,}..."
    )
    print()

    overall_start = time.time()
    chunks_processed = 0
    docs_processed = 0
    batch_num = 0
    batch_chunks = []

    # Stream documents and process in batches
    with open(jsonl_path, "r") as f:
        for line in f:
            if not line.strip():
                continue

            # Parse and convert document to chunk(s)
            data = json.loads(line)
            target_doc = TargetDocument(**data)
            doc_chunks = convert_target_doc_to_chunks(target_doc)
            batch_chunks.extend(doc_chunks)  # Add all chunks from this document
            docs_processed += 1

            # Process batch when full
            if len(batch_chunks) >= batch_size:
                batch_num += 1
                print(f"=== Batch {batch_num}/{num_batches} ===")

                # Embed with Cohere (dense)
                embed_start = time.time()
                dense_embeddings = chunks_to_cohere_embeddings(
                    batch_chunks, cohere_client, cohere_model
                )
                dense_time = time.time() - embed_start

                # Embed with BM25 (sparse)
                sparse_start = time.time()
                sparse_embeddings = chunks_to_bm25_embeddings(
                    batch_chunks, sparse_embedding_model
                )
                sparse_time = time.time() - sparse_start

                # Calculate embedding sizes
                dense_dim = len(dense_embeddings[0].vector) if dense_embeddings else 0
                avg_sparse_dims = (
                    sum(len(e.vector.indices) for e in sparse_embeddings)
                    / len(sparse_embeddings)
                    if sparse_embeddings
                    else 0
                )

                embed_time = dense_time + sparse_time
                print(
                    f"1. Embeddings: {embed_time:.2f}s (dense: {dense_time:.2f}s, sparse: {sparse_time:.2f}s)"
                )
                print(
                    f"   Dense dim: {dense_dim}, Avg sparse dims: {avg_sparse_dims:.0f}"
                )

                # Step 2: Build points with both dense and sparse embeddings
                build_start = time.time()
                points = []
                for chunk, dense_emb, sparse_emb in zip(
                    batch_chunks, dense_embeddings, sparse_embeddings
                ):
                    from qdrant_client.models import PointStruct

                    points.append(
                        PointStruct(
                            id=str(chunk.id),
                            vector={
                                "dense": dense_emb.vector,
                                "sparse": sparse_emb.vector,
                            },
                            payload=chunk.model_dump(exclude={"id"}),
                        )
                    )
                build_time = time.time() - build_start
                print(f"2. Build points: {build_time:.2f}s")

                # Step 3: Insert to Qdrant
                insert_start = time.time()
                result = qdrant_client.override_points(points, collection_name)
                insert_time = time.time() - insert_start
                print(f"3. Insert to Qdrant: {insert_time:.2f}s")

                batch_total = time.time() - embed_start
                chunks_processed += len(batch_chunks)

                print(f"Batch total: {batch_total:.2f}s")
                print(f"Status: {result.status}")
                print(
                    f"Docs: {docs_processed:,} / {total_docs:,} | Chunks: {chunks_processed:,}"
                )
                print()

                # Clear batch for next iteration and free memory aggressively
                del dense_embeddings, sparse_embeddings, points, result
                batch_chunks = []
                gc.collect()

                # Small delay to allow memory cleanup
                time.sleep(0.1)

    # Process remaining chunks if any
    if batch_chunks:
        batch_num += 1
        print(f"=== Batch {batch_num}/{num_batches} (final) ===")

        # Embed with Cohere (dense)
        embed_start = time.time()
        dense_embeddings = chunks_to_cohere_embeddings(
            batch_chunks, cohere_client, cohere_model
        )
        dense_time = time.time() - embed_start

        # Embed with BM25 (sparse)
        sparse_start = time.time()
        sparse_embeddings = chunks_to_bm25_embeddings(
            batch_chunks, sparse_embedding_model
        )
        sparse_time = time.time() - sparse_start

        # Calculate embedding sizes
        dense_dim = len(dense_embeddings[0].vector) if dense_embeddings else 0
        avg_sparse_dims = (
            sum(len(e.vector.indices) for e in sparse_embeddings)
            / len(sparse_embeddings)
            if sparse_embeddings
            else 0
        )

        embed_time = dense_time + sparse_time
        print(
            f"1. Embeddings: {embed_time:.2f}s (dense: {dense_time:.2f}s, sparse: {sparse_time:.2f}s)"
        )
        print(f"   Dense dim: {dense_dim}, Avg sparse dims: {avg_sparse_dims:.0f}")

        # Build points with both dense and sparse embeddings
        build_start = time.time()
        points = []
        for chunk, dense_emb, sparse_emb in zip(
            batch_chunks, dense_embeddings, sparse_embeddings
        ):
            from qdrant_client.models import PointStruct

            points.append(
                PointStruct(
                    id=str(chunk.id),
                    vector={"dense": dense_emb.vector, "sparse": sparse_emb.vector},
                    payload=chunk.model_dump(exclude={"id"}),
                )
            )
        build_time = time.time() - build_start
        print(f"2. Build points: {build_time:.2f}s")

        insert_start = time.time()
        result = qdrant_client.override_points(points, collection_name)
        insert_time = time.time() - insert_start
        print(f"3. Insert to Qdrant: {insert_time:.2f}s")

        batch_total = time.time() - embed_start
        chunks_processed += len(batch_chunks)

        print(f"Batch total: {batch_total:.2f}s")
        print(f"Status: {result.status}")
        print(
            f"Docs: {docs_processed:,} / {total_docs:,} | Chunks: {chunks_processed:,}"
        )
        print()

    total_elapsed = time.time() - overall_start

    print("=" * 60)
    print("COMPLETE")
    print("=" * 60)
    print(f"Total documents processed: {total_docs:,}")
    print(f"Total chunks inserted: {chunks_processed:,}")
    print(f"Average chunks per document: {chunks_processed / total_docs:.1f}")
    print(f"Total time: {total_elapsed:.2f} seconds ({total_elapsed / 60:.1f} minutes)")
    print(f"Average rate: {chunks_processed / total_elapsed:.1f} chunks/sec")
    print()

    print("Collection info:")
    collection_info = qdrant_client.get_collection(collection_name)
    print(f"  Points count: {collection_info.points_count:,}")
    print(f"  Indexed vectors count: {collection_info.indexed_vectors_count:,}")
    print(f"  Optimizer status: {collection_info.optimizer_status}")
    print(f"  Status: {collection_info.status}")

    # Only need to trigger indexing if we disabled it during upload
    if not index_while_uploading:
        print("\nTriggering indexing (was disabled during upload)...")

        qdrant_client.update_collection(
            collection_name=collection_name,
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=20000,
            ),
        )
        print("Collection optimizers config updated - indexing will now proceed")
    else:
        print("\nIndexing was enabled during upload - no manual trigger needed")

    fresh_collection_info = qdrant_client.get_collection(collection_name)
    print(f"  Points count: {fresh_collection_info.points_count:,}")
    print(f"  Indexed vectors count: {fresh_collection_info.indexed_vectors_count:,}")
    print(f"  Optimizer status: {fresh_collection_info.optimizer_status}")
    print(f"  Status: {fresh_collection_info.status}")


if __name__ == "__main__":
    main()
