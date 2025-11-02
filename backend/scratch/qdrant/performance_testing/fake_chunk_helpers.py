import datetime
import random
from uuid import UUID
from uuid import uuid4

from qdrant_client.models import SparseVector

from ..schemas.chunk import QdrantChunk
from ..schemas.embeddings import ChunkDenseEmbedding
from ..schemas.embeddings import ChunkSparseEmbedding
from ..schemas.source_type import SourceType


# Pre-generated pool of 100 emails for consistent ACL testing
_EMAIL_POOL = [f"user_{i:03d}@example.com" for i in range(100)]


def get_email_pool() -> list[str]:
    """Get the pool of 100 pre-generated emails."""
    return _EMAIL_POOL


def fake_email() -> str:
    """Get a random email from the pool."""
    return random.choice(_EMAIL_POOL)


def fake_content() -> str:
    words = [
        "lorem",
        "ipsum",
        "dolor",
        "sit",
        "amet",
        "consectetur",
        "adipiscing",
        "elit",
        "sed",
        "do",
        "eiusmod",
        "tempor",
    ]
    return " ".join(random.choices(words, k=random.randint(10, 30)))


def fake_source_type() -> SourceType:
    return random.choice(list(SourceType))


def fake_created_at() -> datetime.datetime:
    """
    Generate a fake creation datetime within the last year.

    Returns:
        A random datetime between 365 days ago and now
    """
    now = datetime.datetime.now()
    days_ago = random.randint(0, 365)
    hours_ago = random.randint(0, 23)
    minutes_ago = random.randint(0, 59)

    fake_time = now - datetime.timedelta(
        days=days_ago, hours=hours_ago, minutes=minutes_ago
    )
    return fake_time


def fake_acl() -> list[str]:
    """
    Generate a fake ACL with 1-3 random emails from the pool.
    This ensures overlap between chunks for realistic filtering tests.
    """
    num_emails = random.randint(1, 3)
    return random.sample(_EMAIL_POOL, num_emails)


def generate_fake_qdrant_chunks(n: int, content: str | None = None):
    """
    Generator that yields n fake QdrantChunk objects.

    Args:
        n: Number of chunks to generate
        content: Optional fixed content for all chunks. If None, generates random content.
    """
    for _ in range(n):
        yield QdrantChunk(
            id=uuid4(),
            document_id=uuid4(),
            source_type=fake_source_type(),
            access_control_list=fake_acl(),
            created_at=fake_created_at(),
            content=content if content is not None else fake_content(),
        )


def fake_dense_embedding(chunk_id: UUID, vector_size: int = 768) -> ChunkDenseEmbedding:
    """
    Generate a fake dense embedding with random values.

    Args:
        chunk_id: The chunk UUID
        vector_size: Dimension of the dense vector (default 768 for nomic-embed)
    """
    # Generate random normalized vector
    vector = [random.uniform(-1, 1) for _ in range(vector_size)]
    return ChunkDenseEmbedding(chunk_id=chunk_id, vector=vector)


def fake_sparse_embedding(chunk_id: UUID, num_dims: int = 100) -> ChunkSparseEmbedding:
    """
    Generate a fake sparse embedding with random indices and values.

    Args:
        chunk_id: The chunk UUID
        num_dims: Number of non-zero dimensions in the sparse vector
    """
    # Generate random indices (sorted, no duplicates)
    indices = sorted(random.sample(range(30000), num_dims))
    # Generate random values (typical range for sparse embeddings)
    values = [random.uniform(0, 2) for _ in range(num_dims)]

    sparse_vector = SparseVector(indices=indices, values=values)
    return ChunkSparseEmbedding(chunk_id=chunk_id, vector=sparse_vector)


def generate_fake_embeddings_for_chunks(
    chunks: list[QdrantChunk],
    vector_size: int = 768,
    sparse_dims: int = 100,
) -> tuple[list[ChunkDenseEmbedding], list[ChunkSparseEmbedding]]:
    """
    Generate fake embeddings for a batch of chunks.
    Much faster than real embedding models for load testing.

    Args:
        chunks: List of chunks to generate embeddings for
        vector_size: Dimension of dense vectors
        sparse_dims: Number of non-zero dimensions in sparse vectors

    Returns:
        Tuple of (dense_embeddings, sparse_embeddings)
    """
    dense_embeddings = [fake_dense_embedding(chunk.id, vector_size) for chunk in chunks]
    sparse_embeddings = [
        fake_sparse_embedding(chunk.id, sparse_dims) for chunk in chunks
    ]
    return dense_embeddings, sparse_embeddings
