from typing import TypeVar

from sqlalchemy.orm import Session

from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SavedSearchDocWithContent
from onyx.context.search.models import SearchDoc
from onyx.db.search_settings import get_current_search_settings
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time
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


# If it should be a real section, don't use this one
def inference_section_from_single_chunk(
    chunk: InferenceChunk,
) -> InferenceSection:
    return InferenceSection(
        center_chunk=chunk,
        chunks=[chunk],
        combined_content=chunk.content,
    )


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


@log_function_time(print_only=True, debug_only=True)
def get_query_embedding(query: str, db_session: Session) -> Embedding:
    return get_query_embeddings([query], db_session)[0]


def convert_inference_sections_to_search_docs(
    inference_sections: list[InferenceSection],
    is_internet: bool = False,
) -> list[SearchDoc]:
    search_docs = SearchDoc.from_chunks_or_sections(inference_sections)
    for search_doc in search_docs:
        search_doc.is_internet = is_internet
    return search_docs
