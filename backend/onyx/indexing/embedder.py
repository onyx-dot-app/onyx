import time
from abc import ABC
from abc import abstractmethod
from collections import defaultdict

from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.models import DocumentFailure
from onyx.db.models import SearchSettings
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import IndexChunk
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import INDEXING_MODEL_SERVER_PORT
from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import Embedding


logger = setup_logger()


class IndexingEmbedder(ABC):
    """Converts chunks into chunks with embeddings. Note that one chunk may have
    multiple embeddings associated with it."""

    def __init__(
        self,
        model_name: str,
        normalize: bool,
        query_prefix: str | None,
        passage_prefix: str | None,
        provider_type: EmbeddingProvider | None,
        api_key: str | None,
        api_url: str | None,
        api_version: str | None,
        deployment_name: str | None,
        reduced_dimension: int | None,
        callback: IndexingHeartbeatInterface | None,
    ):
        self.model_name = model_name
        self.normalize = normalize
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.provider_type = provider_type
        self.api_key = api_key
        self.api_url = api_url
        self.api_version = api_version
        self.deployment_name = deployment_name

        self.embedding_model = EmbeddingModel(
            model_name=model_name,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            normalize=normalize,
            api_key=api_key,
            provider_type=provider_type,
            api_url=api_url,
            api_version=api_version,
            deployment_name=deployment_name,
            reduced_dimension=reduced_dimension,
            # The below are globally set, this flow always uses the indexing one
            server_host=INDEXING_MODEL_SERVER_HOST,
            server_port=INDEXING_MODEL_SERVER_PORT,
            retrim_content=True,
            callback=callback,
        )

    @abstractmethod
    def embed_chunks(
        self,
        chunks: list[DocAwareChunk],
        tenant_id: str | None = None,
        request_id: str | None = None,
    ) -> list[IndexChunk]:
        raise NotImplementedError


class DefaultIndexingEmbedder(IndexingEmbedder):
    def __init__(
        self,
        model_name: str,
        normalize: bool,
        query_prefix: str | None,
        passage_prefix: str | None,
        provider_type: EmbeddingProvider | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        reduced_dimension: int | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ):
        super().__init__(
            model_name,
            normalize,
            query_prefix,
            passage_prefix,
            provider_type,
            api_key,
            api_url,
            api_version,
            deployment_name,
            reduced_dimension,
            callback,
        )

    @log_function_time()
    def embed_chunks(
        self,
        chunks: list[DocAwareChunk],
        tenant_id: str | None = None,
        request_id: str | None = None,
    ) -> list[IndexChunk]:
        """Adds embeddings to the chunks, the title and metadata suffixes are added to the chunk as well
        if they exist. If there is no space for it, it would have been thrown out at the chunking step.
        """
        # All chunks at this point must have some non-empty content
        flat_chunk_texts: list[str] = []
        large_chunks_present = False
        for chunk in chunks:
            if chunk.large_chunk_reference_ids:
                large_chunks_present = True
            chunk_text = (
                f"{chunk.title_prefix}{chunk.doc_summary}{chunk.content}{chunk.chunk_context}{chunk.metadata_suffix_semantic}"
            ) or chunk.source_document.get_title_for_document_index()

            if not chunk_text:
                # This should never happen, the document would have been dropped
                # before getting to this point
                raise ValueError(f"Chunk has no content: {chunk.to_short_descriptor()}")

            flat_chunk_texts.append(chunk_text)

            if chunk.mini_chunk_texts:
                if chunk.large_chunk_reference_ids:
                    # A large chunk does not contain mini chunks, if it matches the large chunk
                    # with a high score, then mini chunks would not be used anyway
                    # otherwise it should match the normal chunk
                    raise RuntimeError("Large chunk contains mini chunks")
                flat_chunk_texts.extend(chunk.mini_chunk_texts)

        embeddings = self.embedding_model.encode(
            texts=flat_chunk_texts,
            text_type=EmbedTextType.PASSAGE,
            large_chunks_present=large_chunks_present,
            tenant_id=tenant_id,
            request_id=request_id,
        )

        chunk_titles = {
            chunk.source_document.get_title_for_document_index() for chunk in chunks
        }

        # Drop any None or empty strings
        # If there is no title or the title is empty, the title embedding field will be null
        # which is ok, it just won't contribute at all to the scoring.
        chunk_titles_list = [title for title in chunk_titles if title]

        # Cache the Title embeddings to only have to do it once
        title_embed_dict: dict[str, Embedding] = {}
        if chunk_titles_list:
            title_embeddings = self.embedding_model.encode(
                chunk_titles_list,
                text_type=EmbedTextType.PASSAGE,
                tenant_id=tenant_id,
                request_id=request_id,
            )
            title_embed_dict.update(
                {
                    title: vector
                    for title, vector in zip(chunk_titles_list, title_embeddings)
                }
            )

        # Mapping embeddings to chunks
        embedded_chunks: list[IndexChunk] = []
        embedding_ind_start = 0
        for chunk in chunks:
            num_embeddings = 1 + (
                len(chunk.mini_chunk_texts) if chunk.mini_chunk_texts else 0
            )
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
                        [title],
                        text_type=EmbedTextType.PASSAGE,
                        tenant_id=tenant_id,
                        request_id=request_id,
                    )[0]
                    title_embed_dict[title] = title_embedding

            new_embedded_chunk = IndexChunk(
                **chunk.model_dump(),
                embeddings=ChunkEmbedding(
                    full_embedding=chunk_embeddings[0],
                    mini_chunk_embeddings=chunk_embeddings[1:],
                ),
                title_embedding=title_embedding,
            )
            embedded_chunks.append(new_embedded_chunk)
            embedding_ind_start += num_embeddings

        return embedded_chunks

    @classmethod
    def from_db_search_settings(
        cls,
        search_settings: SearchSettings,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> "DefaultIndexingEmbedder":
        return cls(
            model_name=search_settings.model_name,
            normalize=search_settings.normalize,
            query_prefix=search_settings.query_prefix,
            passage_prefix=search_settings.passage_prefix,
            provider_type=search_settings.provider_type,
            api_key=search_settings.api_key,
            api_url=search_settings.api_url,
            api_version=search_settings.api_version,
            deployment_name=search_settings.deployment_name,
            reduced_dimension=search_settings.reduced_dimension,
            callback=callback,
        )


def embed_chunks_with_failure_handling(
    chunks: list[DocAwareChunk],
    embedder: IndexingEmbedder,
    tenant_id: str | None = None,
    request_id: str | None = None,
) -> tuple[list[IndexChunk], list[ConnectorFailure]]:
    """Tries to embed all chunks in one large batch. If that batch fails for any reason,
    goes document by document to isolate the failure(s).
    """

    # TODO(rkuo): this doesn't disambiguate calls to the model server on retries.
    # Improve this if needed.

    # First try to embed all chunks in one batch
    try:
        return (
            embedder.embed_chunks(
                chunks=chunks, tenant_id=tenant_id, request_id=request_id
            ),
            [],
        )
    except ConnectorStopSignal as e:
        logger.warning(
            "Connector stop signal detected in embed_chunks_with_failure_handling"
        )
        raise e
    except Exception:
        logger.exception("Failed to embed chunk batch. Trying individual docs.")
        # wait a couple seconds to let any rate limits or temporary issues resolve
        time.sleep(2)

    # Try embedding each document's chunks individually
    chunks_by_doc: dict[str, list[DocAwareChunk]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_doc[chunk.source_document.id].append(chunk)

    embedded_chunks: list[IndexChunk] = []
    failures: list[ConnectorFailure] = []

    for doc_id, chunks_for_doc in chunks_by_doc.items():
        try:
            doc_embedded_chunks = embedder.embed_chunks(
                chunks=chunks_for_doc, tenant_id=tenant_id, request_id=request_id
            )
            embedded_chunks.extend(doc_embedded_chunks)
        except Exception as e:
            logger.exception(f"Failed to embed chunks for document '{doc_id}'")
            failures.append(
                ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=doc_id,
                        document_link=(
                            chunks_for_doc[0].get_link() if chunks_for_doc else None
                        ),
                    ),
                    failure_message=str(e),
                    exception=e,
                )
            )

    return embedded_chunks, failures
