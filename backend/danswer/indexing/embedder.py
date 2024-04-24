from abc import ABC
from abc import abstractmethod

from sqlalchemy.orm import Session

from danswer.configs.app_configs import ENABLE_MINI_CHUNK
from danswer.configs.model_configs import BATCH_SIZE_ENCODE_CHUNKS
from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.embedding_model import get_secondary_db_embedding_model
from danswer.db.models import EmbeddingModel as DbEmbeddingModel
from danswer.db.models import IndexModelStatus
from danswer.indexing.chunker import split_chunk_text_into_mini_chunks
from danswer.indexing.models import ChunkEmbedding
from danswer.indexing.models import DocAwareChunk
from danswer.indexing.models import IndexChunk
from danswer.search.enums import EmbedTextType
from danswer.search.search_nlp_models import EmbeddingModel
from danswer.utils.batching import batch_list
from danswer.utils.logger import setup_logger
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT


logger = setup_logger()


class IndexingEmbedder(ABC):
    def __init__(
        self,
        model_name: str,
        normalize: bool,
        query_prefix: str | None,
        passage_prefix: str | None,
    ):
        self.model_name = model_name
        self.normalize = normalize
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix

    @abstractmethod
    def embed_chunks(self, chunks: list[DocAwareChunk]) -> list[IndexChunk]:
        raise NotImplementedError


class DefaultIndexingEmbedder(IndexingEmbedder):
    def __init__(
        self,
        model_name: str,
        normalize: bool,
        query_prefix: str | None,
        passage_prefix: str | None,
    ):
        super().__init__(model_name, normalize, query_prefix, passage_prefix)
        self.max_seq_length = DOC_EMBEDDING_CONTEXT_SIZE  # Currently not customizable

        self.embedding_model = EmbeddingModel(
            model_name=model_name,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            normalize=normalize,
            # The below are globally set, this flow always uses the indexing one
            server_host=INDEXING_MODEL_SERVER_HOST,
            server_port=MODEL_SERVER_PORT,
        )

    def embed_chunks(
        self,
        chunks: list[DocAwareChunk],
        batch_size: int = BATCH_SIZE_ENCODE_CHUNKS,
        enable_mini_chunk: bool = ENABLE_MINI_CHUNK,
    ) -> list[IndexChunk]:
        # Cache the Title embeddings to only have to do it once
        title_embed_dict: dict[str, list[float]] = {}
        embedded_chunks: list[IndexChunk] = []

        # Create Mini Chunks for more precise matching of details
        # Off by default with unedited settings
        chunk_texts = []
        chunk_mini_chunks_count = {}
        for chunk_ind, chunk in enumerate(chunks):
            chunk_texts.append(chunk.content)
            mini_chunk_texts = (
                split_chunk_text_into_mini_chunks(chunk.content)
                if enable_mini_chunk
                else []
            )
            chunk_texts.extend(mini_chunk_texts)
            chunk_mini_chunks_count[chunk_ind] = 1 + len(mini_chunk_texts)

        # Batching for embedding
        text_batches = batch_list(chunk_texts, batch_size)

        embeddings: list[list[float]] = []
        len_text_batches = len(text_batches)
        for idx, text_batch in enumerate(text_batches, start=1):
            logger.debug(f"Embedding Content Texts batch {idx} of {len_text_batches}")
            # Normalize embeddings is only configured via model_configs.py, be sure to use right
            # value for the set loss
            embeddings.extend(
                self.embedding_model.encode(text_batch, text_type=EmbedTextType.PASSAGE)
            )

            # Replace line above with the line below for easy debugging of indexing flow
            # skipping the actual model
            # embeddings.extend([[0.0] * 384 for _ in range(len(text_batch))])

        chunk_titles = {
            chunk.source_document.get_title_for_document_index() for chunk in chunks
        }

        # Drop any None or empty strings
        chunk_titles_list = [title for title in chunk_titles if title]

        # Embed Titles in batches
        title_batches = batch_list(chunk_titles_list, batch_size)
        len_title_batches = len(title_batches)
        for ind_batch, title_batch in enumerate(title_batches, start=1):
            logger.debug(f"Embedding Titles batch {ind_batch} of {len_title_batches}")
            title_embeddings = self.embedding_model.encode(
                title_batch, text_type=EmbedTextType.PASSAGE
            )
            title_embed_dict.update(
                {title: vector for title, vector in zip(title_batch, title_embeddings)}
            )

        # Mapping embeddings to chunks
        embedding_ind_start = 0
        for chunk_ind, chunk in enumerate(chunks):
            num_embeddings = chunk_mini_chunks_count[chunk_ind]
            chunk_embeddings = embeddings[
                embedding_ind_start : embedding_ind_start + num_embeddings
            ]

            title = chunk.source_document.get_title_for_document_index()

            title_embedding = None
            if title:
                if title in title_embed_dict:
                    # Using cached value to avoid recalculating for every chunk
                    title_embedding = title_embed_dict[title]
                else:
                    logger.error(
                        "Title had to be embedded separately, this should not happen!"
                    )
                    title_embedding = self.embedding_model.encode(
                        [title], text_type=EmbedTextType.PASSAGE
                    )[0]
                    title_embed_dict[title] = title_embedding

            new_embedded_chunk = IndexChunk(
                **chunk.dict(),
                embeddings=ChunkEmbedding(
                    full_embedding=chunk_embeddings[0],
                    mini_chunk_embeddings=chunk_embeddings[1:],
                ),
                title_embedding=title_embedding,
            )
            embedded_chunks.append(new_embedded_chunk)
            embedding_ind_start += num_embeddings

        return embedded_chunks


def get_embedding_model_from_db_embedding_model(
    db_session: Session, index_model_status: IndexModelStatus = IndexModelStatus.PRESENT
) -> IndexingEmbedder:
    db_embedding_model: DbEmbeddingModel | None
    if index_model_status == IndexModelStatus.PRESENT:
        db_embedding_model = get_current_db_embedding_model(db_session)
    elif index_model_status == IndexModelStatus.FUTURE:
        db_embedding_model = get_secondary_db_embedding_model(db_session)
        if not db_embedding_model:
            raise RuntimeError("No secondary index configured")
    else:
        raise RuntimeError("Not supporting embedding model rollbacks")

    return DefaultIndexingEmbedder(
        model_name=db_embedding_model.model_name,
        normalize=db_embedding_model.normalize,
        query_prefix=db_embedding_model.query_prefix,
        passage_prefix=db_embedding_model.passage_prefix,
    )
