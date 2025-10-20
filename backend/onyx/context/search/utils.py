import string
from collections.abc import Sequence
from typing import TypeVar

from sqlalchemy.orm import Session

from onyx.chat.models import SectionRelevancePiece
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SavedSearchDocWithContent
from onyx.context.search.models import SearchDoc
from onyx.db.models import SearchDoc as DBSearchDoc
from onyx.db.search_settings import get_current_search_settings
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.utils.logger import setup_logger
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import Embedding

logger = setup_logger()


T = TypeVar(
    "T",
    InferenceSection,
    InferenceChunk,
    SearchDoc,
    SavedSearchDoc,
    SavedSearchDocWithContent,
)

TSection = TypeVar(
    "TSection",
    InferenceSection,
    SearchDoc,
    SavedSearchDoc,
    SavedSearchDocWithContent,
)


def dedupe_documents(items: list[T]) -> tuple[list[T], list[int]]:
    seen_ids = set()
    deduped_items = []
    dropped_indices = []
    for index, item in enumerate(items):
        if isinstance(item, InferenceSection):
            document_id = item.center_chunk.document_id
        else:
            document_id = item.document_id

        if document_id not in seen_ids:
            seen_ids.add(document_id)
            deduped_items.append(item)
        else:
            dropped_indices.append(index)
    return deduped_items, dropped_indices


def relevant_sections_to_indices(
    relevance_sections: list[SectionRelevancePiece] | None, items: list[TSection]
) -> list[int]:
    if not relevance_sections:
        return []

    relevant_set = {
        (chunk.document_id, chunk.chunk_id)
        for chunk in relevance_sections
        if chunk.relevant
    }

    return [
        index
        for index, item in enumerate(items)
        if (
            (
                isinstance(item, InferenceSection)
                and (item.center_chunk.document_id, item.center_chunk.chunk_id)
                in relevant_set
            )
            or (
                not isinstance(item, (InferenceSection))
                and (item.document_id, item.chunk_ind) in relevant_set
            )
        )
    ]


def drop_llm_indices(
    llm_indices: list[int],
    search_docs: Sequence[DBSearchDoc | SavedSearchDoc],
    dropped_indices: list[int],
) -> list[int]:
    llm_bools = [i in llm_indices for i in range(len(search_docs))]
    if dropped_indices:
        llm_bools = [
            val for ind, val in enumerate(llm_bools) if ind not in dropped_indices
        ]
    return [i for i, val in enumerate(llm_bools) if val]


def inference_section_from_chunks(
    center_chunk: InferenceChunk,
    chunks: list[InferenceChunk],
) -> InferenceSection | None:
    if not chunks:
        return None

    combined_content = "\n".join([chunk.content for chunk in chunks])

    return InferenceSection(
        center_chunk=center_chunk,
        chunks=chunks,
        combined_content=combined_content,
    )


def remove_stop_words_and_punctuation(keywords: list[str]) -> list[str]:
    from nltk.corpus import stopwords  # type:ignore
    from nltk.tokenize import word_tokenize  # type:ignore

    try:
        # Re-tokenize using the NLTK tokenizer for better matching
        query = " ".join(keywords)
        stop_words = set(stopwords.words("english"))
        word_tokens = word_tokenize(query)
        text_trimmed = [
            word
            for word in word_tokens
            if (word.casefold() not in stop_words and word not in string.punctuation)
        ]
        return text_trimmed or word_tokens
    except Exception as e:
        logger.warning(f"Error removing stop words and punctuation: {e}")
        return keywords


def get_query_embeddings(queries: list[str], db_session: Session) -> list[Embedding]:
    search_settings = get_current_search_settings(db_session)

    model = EmbeddingModel.from_db_model(
        search_settings=search_settings,
        # The below are globally set, this flow always uses the indexing one
        server_host=MODEL_SERVER_HOST,
        server_port=MODEL_SERVER_PORT,
    )

    query_embedding = model.encode(queries, text_type=EmbedTextType.QUERY)
    return query_embedding


def get_query_embedding(query: str, db_session: Session) -> Embedding:
    return get_query_embeddings([query], db_session)[0]
