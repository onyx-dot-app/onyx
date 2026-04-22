import os
import re
from typing import TypeVar

from sqlalchemy.orm import Session

from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SavedSearchDocWithContent
from onyx.context.search.models import SearchDoc
from onyx.db.document import get_document_id_to_file_id_map
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

_UNSAFE_CHARS_RE = re.compile(r"[\x00-\x1f/\\:\*\?\"<>\|]+")
_SANDBOX_FILENAME_MAX_LENGTH = 200


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


def get_query_embeddings(
    queries: list[str],
    db_session: Session | None = None,
    embedding_model: EmbeddingModel | None = None,
) -> list[Embedding]:
    if embedding_model is None:
        if db_session is None:
            raise ValueError("Either db_session or embedding_model must be provided")
        search_settings = get_current_search_settings(db_session)
        embedding_model = EmbeddingModel.from_db_model(
            search_settings=search_settings,
            server_host=MODEL_SERVER_HOST,
            server_port=MODEL_SERVER_PORT,
        )

    query_embedding = embedding_model.encode(queries, text_type=EmbedTextType.QUERY)
    return query_embedding


@log_function_time(print_only=True, debug_only=True)
def get_query_embedding(
    query: str,
    db_session: Session | None = None,
    embedding_model: EmbeddingModel | None = None,
) -> Embedding:
    return get_query_embeddings(
        [query], db_session=db_session, embedding_model=embedding_model
    )[0]


def convert_inference_sections_to_search_docs(
    inference_sections: list[InferenceSection],
    is_internet: bool = False,
) -> list[SearchDoc]:
    search_docs = SearchDoc.from_chunks_or_sections(inference_sections)
    for search_doc in search_docs:
        search_doc.is_internet = is_internet
    return search_docs


def sandbox_filename_for_document(title: str, file_id: str) -> str:
    """Sanitize a document title and append its file_id to produce a globally
    unique sandbox filename. Extensions on the title are preserved verbatim."""
    sanitized = _UNSAFE_CHARS_RE.sub("_", title).strip().strip(".")
    base, ext = os.path.splitext(sanitized)
    if not base:
        base = "document"
    suffix = f"_{file_id}{ext}"
    max_base_len = max(1, _SANDBOX_FILENAME_MAX_LENGTH - len(suffix))
    return f"{base[:max_base_len]}{suffix}"


def populate_file_ids_on_sections(
    sections: list[InferenceSection],
    db_session: Session,
) -> None:
    """Stamp `Document.file_id` onto every chunk in-place."""
    if not sections:
        return

    document_ids = list({section.center_chunk.document_id for section in sections})
    file_id_map = get_document_id_to_file_id_map(
        db_session=db_session, document_ids=document_ids
    )
    if not file_id_map:
        return

    for section in sections:
        # Set on every chunk so the section's chunks stay consistent with
        # center_chunk regardless of which one downstream code looks at.
        for chunk in (section.center_chunk, *section.chunks):
            file_id = file_id_map.get(chunk.document_id)
            if file_id is not None:
                chunk.file_id = file_id
