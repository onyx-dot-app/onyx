from abc import ABC
from abc import abstractmethod

from sqlalchemy.orm import Session

from danswer.configs.app_configs import ENABLE_MINI_CHUNK
from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.embedding_model import get_secondary_db_embedding_model
from danswer.db.models import EmbeddingModel as DbEmbeddingModel
from danswer.db.models import IndexModelStatus
from danswer.indexing.chunker import split_chunk_text_into_mini_chunks
from danswer.indexing.models import ChunkEmbedding
from danswer.indexing.models import DocAwareChunk
from danswer.indexing.models import IndexChunk
from danswer.natural_language_processing.search_nlp_models import EmbeddingModel
from danswer.utils.logger import setup_logger
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import INDEXING_MODEL_SERVER_PORT
from shared_configs.enums import EmbedTextType


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
        api_key: str | None = None,
        provider_type: str | None = None,
    ):
        super().__init__(model_name, normalize, query_prefix, passage_prefix)
        self.max_seq_length = DOC_EMBEDDING_CONTEXT_SIZE  # Currently not customizable

        self.embedding_model = EmbeddingModel(
            model_name=model_name,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            normalize=normalize,
            api_key=api_key,
            provider_type=provider_type,
            # The below are globally set, this flow always uses the indexing one
            server_host=INDEXING_MODEL_SERVER_HOST,
            server_port=INDEXING_MODEL_SERVER_PORT,
            retrim_content=True,
        )

    def embed_chunks(
        self,
        chunks: list[DocAwareChunk],
        enable_mini_chunk: bool = ENABLE_MINI_CHUNK,
    ) -> list[IndexChunk]:
        # Cache the Title embeddings to only have to do it once
        title_embed_dict: dict[str, list[float] | None] = {}
        embedded_chunks: list[IndexChunk] = []

        # Create Mini Chunks for more precise matching of details
        # Off by default with unedited settings
        chunk_texts: list[str] = []
        chunk_mini_chunks_count = {}
        for chunk_ind, chunk in enumerate(chunks):
            # The whole chunk including the prefix/suffix is included in the overall vector representation
            chunk_texts.append(
                f"{chunk.title_prefix}{chunk.content}{chunk.metadata_suffix_semantic}"
            )
            mini_chunk_texts = (
                split_chunk_text_into_mini_chunks(chunk.content)
                if enable_mini_chunk
                else []
            )
            chunk_texts.extend(mini_chunk_texts)
            chunk_mini_chunks_count[chunk_ind] = 1 + len(mini_chunk_texts)

        embeddings = self.embedding_model.encode(
            chunk_texts, text_type=EmbedTextType.PASSAGE
        )

        chunk_titles = {
            chunk.source_document.get_title_for_document_index() for chunk in chunks
        }

        # Drop any None or empty strings
        chunk_titles_list = [title for title in chunk_titles if title]

        if chunk_titles_list:
            title_embeddings = self.embedding_model.encode(
                chunk_titles_list, text_type=EmbedTextType.PASSAGE
            )
            title_embed_dict.update(
                {
                    title: vector
                    for title, vector in zip(chunk_titles_list, title_embeddings)
                }
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
        provider_type=db_embedding_model.provider_type,
        api_key=db_embedding_model.api_key,
    )
