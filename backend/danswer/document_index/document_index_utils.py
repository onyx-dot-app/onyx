import math
import uuid

from sqlalchemy.orm import Session

from danswer.context.search.models import InferenceChunk
from danswer.db.search_settings import get_current_search_settings
from danswer.db.search_settings import get_secondary_search_settings
from danswer.indexing.models import IndexChunk


DEFAULT_BATCH_SIZE = 30
DEFAULT_INDEX_NAME = "danswer_chunk"


def get_both_index_names(db_session: Session) -> tuple[str, str | None]:
    search_settings = get_current_search_settings(db_session)

    search_settings_new = get_secondary_search_settings(db_session)
    if not search_settings_new:
        return search_settings.index_name, None

    return search_settings.index_name, search_settings_new.index_name


def translate_boost_count_to_multiplier(boost: int) -> float:
    """Mapping boost integer values to a multiplier according to a sigmoid curve
    Piecewise such that at many downvotes, its 0.5x the score and with many upvotes
    it is 2x the score. This should be in line with the Vespa calculation."""
    # 3 in the equation below stretches it out to hit asymptotes slower
    if boost < 0:
        # 0.5 + sigmoid -> range of 0.5 to 1
        return 0.5 + (1 / (1 + math.exp(-1 * boost / 3)))

    # 2 x sigmoid -> range of 1 to 2
    return 2 / (1 + math.exp(-1 * boost / 3))


def get_uuid_from_chunk(
    chunk: IndexChunk | InferenceChunk, mini_chunk_ind: int = 0
) -> uuid.UUID:
    doc_str = (
        chunk.document_id
        if isinstance(chunk, InferenceChunk)
        else chunk.source_document.id
    )
    # Web parsing URL duplicate catching
    if doc_str and doc_str[-1] == "/":
        doc_str = doc_str[:-1]
    unique_identifier_string = "_".join(
        [doc_str, str(chunk.chunk_id), str(mini_chunk_ind)]
    )
    if chunk.large_chunk_reference_ids:
        unique_identifier_string += "_large" + "_".join(
            [
                str(referenced_chunk_id)
                for referenced_chunk_id in chunk.large_chunk_reference_ids
            ]
        )
    return uuid.uuid5(uuid.NAMESPACE_X500, unique_identifier_string)
