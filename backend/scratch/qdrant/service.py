from fastembed import SparseTextEmbedding
from fastembed import TextEmbedding
from qdrant_client.models import Filter
from qdrant_client.models import Fusion
from qdrant_client.models import FusionQuery
from qdrant_client.models import PointStruct
from qdrant_client.models import Prefetch
from qdrant_client.models import SparseVector
from qdrant_client.models import UpdateResult

from scratch.qdrant.client import QdrantClient
from scratch.qdrant.schemas.chunk import QdrantChunk
from scratch.qdrant.schemas.collection_name import CollectionName
from scratch.qdrant.schemas.embeddings import ChunkDenseEmbedding
from scratch.qdrant.schemas.embeddings import ChunkSparseEmbedding


class QdrantService:
    def __init__(self, client: QdrantClient):
        self.client = client

    def embed_chunks_to_dense_embeddings(
        self,
        chunks: list[QdrantChunk],
        dense_embedding_model: TextEmbedding,
    ) -> list[ChunkDenseEmbedding]:
        dense_vectors = dense_embedding_model.passage_embed(
            [chunk.content for chunk in chunks]
        )
        return [
            ChunkDenseEmbedding(chunk_id=chunk.id, vector=vector.tolist())
            for chunk, vector in zip(chunks, dense_vectors)
        ]

    def embed_chunks_to_sparse_embeddings(
        self,
        chunks: list[QdrantChunk],
        sparse_embedding_model: SparseTextEmbedding,
    ) -> list[ChunkSparseEmbedding]:
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

    def build_points_from_chunks_and_embeddings(
        self,
        chunks: list[QdrantChunk],
        dense_embeddings: list[ChunkDenseEmbedding],
        sparse_embeddings: list[ChunkSparseEmbedding],
    ) -> list[PointStruct]:
        """Build PointStruct objects from chunks and their embeddings."""
        # Create lookup maps by chunk_id for explicit matching
        dense_emb_map = {emb.chunk_id: emb for emb in dense_embeddings}
        sparse_emb_map = {emb.chunk_id: emb for emb in sparse_embeddings}

        # Build points from chunks and embeddings matched by chunk_id
        points = []
        for chunk in chunks:
            dense_emb = dense_emb_map[chunk.id]
            sparse_emb = sparse_emb_map[chunk.id]

            points.append(
                PointStruct(
                    id=str(chunk.id),
                    vector={"dense": dense_emb.vector, "sparse": sparse_emb.vector},
                    payload=chunk.model_dump(exclude={"id"}),
                )
            )
        return points

    def embed_and_upsert_chunks(
        self,
        chunks: list[QdrantChunk],
        dense_embedding_model: TextEmbedding,
        sparse_embedding_model: SparseTextEmbedding,
        collection_name: CollectionName,
    ) -> UpdateResult:
        # Use the embedding methods to get structured embeddings
        dense_embeddings = self.embed_chunks_to_dense_embeddings(
            chunks, dense_embedding_model
        )
        sparse_embeddings = self.embed_chunks_to_sparse_embeddings(
            chunks, sparse_embedding_model
        )

        # Build points using the helper method
        points = self.build_points_from_chunks_and_embeddings(
            chunks, dense_embeddings, sparse_embeddings
        )

        update_result = self.client.override_points(
            points=points,
            collection_name=collection_name,
        )

        return update_result

    def dense_search(
        self,
        query_text: str,
        dense_embedding_model: TextEmbedding,
        collection_name: CollectionName,
        limit: int = 10,
        query_filter: Filter | None = None,
    ):
        """Perform dense vector search only."""
        # Generate query embedding
        dense_query_vector = next(
            dense_embedding_model.query_embed(query_text)
        ).tolist()

        # Query with dense vector only
        return self.client.query_points(
            collection_name=collection_name,
            query=dense_query_vector,
            using="dense",
            query_filter=query_filter,
            with_payload=True,
            limit=limit,
        )

    def generate_query_embeddings(  # should live in different service, here for convenience purposes for testing
        self,
        query_text: str,
        dense_embedding_model: TextEmbedding,
        sparse_embedding_model: SparseTextEmbedding,
    ) -> tuple[list[float], SparseVector]:
        """
        Generate dense and sparse embeddings for a query.
        Separated out so you can time just the search without embedding overhead.

        Returns:
            Tuple of (dense_vector, sparse_vector)
        """
        dense_query_vector = next(
            dense_embedding_model.query_embed(query_text)
        ).tolist()
        sparse_embedding = next(sparse_embedding_model.query_embed(query_text))
        sparse_query_vector = SparseVector(
            indices=sparse_embedding.indices.tolist(),
            values=sparse_embedding.values.tolist(),
        )
        return dense_query_vector, sparse_query_vector

    def hybrid_search(
        self,
        dense_query_vector: list[float],
        sparse_query_vector: SparseVector,
        collection_name: CollectionName,
        limit: int = 10,
        prefetch_limit: int | None = None,
        query_filter: Filter | None = None,
        fusion: Fusion = Fusion.DBSF,
    ):
        """
        Perform hybrid search using fusion of dense and sparse vectors.

        Use generate_query_embeddings() first to get vectors from text.
        This keeps embedding time separate from search time for benchmarking.
        """
        # If prefetch_limit not specified, use limit * 2 to ensure we get enough results
        effective_prefetch_limit = (
            prefetch_limit if prefetch_limit is not None else limit * 2
        )

        # Query with fusion
        # Note: With prefetch + fusion, filters must be applied to prefetch queries
        return self.client.query_points(
            collection_name=collection_name,
            prefetch=[
                Prefetch(
                    query=sparse_query_vector,
                    using="sparse",
                    limit=effective_prefetch_limit,
                    filter=query_filter,  # Apply filter to prefetch
                ),
                Prefetch(
                    query=dense_query_vector,
                    using="dense",
                    limit=effective_prefetch_limit,
                    filter=query_filter,  # Apply filter to prefetch
                ),
            ],
            fusion_query=FusionQuery(fusion=fusion),
            with_payload=True,
            limit=limit,
        )
