import math
import uuid

from sqlalchemy.orm import Session

from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_secondary_search_settings
from onyx.document_index.vespa.indexing_utils import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.indexing.models import DocChunkIDInformation
from onyx.indexing.models import DocMetadataAwareIndexChunk


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


def _check_for_chunk_existence(vespa_chunk_id, index_name: str) -> bool:
    vespa_url = f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{vespa_chunk_id}"
    with get_vespa_http_client(no_timeout=True) as http_client:
        res = http_client.get(vespa_url)
        return res.status_code == 200


def check_for_final_chunk_existence(
    document_id_info: DocChunkIDInformation, start_index: int, index_name: str
) -> int:
    index = start_index
    while True:
        doc_chunk_id = get_uuid_from_chunk_info_old(
            document_id=document_id_info.doc_id,
            chunk_id=index,
            large_chunk_reference_ids=[],
        )
        if not _check_for_chunk_existence(doc_chunk_id, index_name):
            return index

        index += 1


def assemble_document_chunk_info(
    document_id_info_list: list[DocChunkIDInformation],
    tenant_id: str | None,
    large_chunks_enabled: bool,
) -> list[uuid.UUID, None, None]:
    doc_chunk_ids = []

    for document_id_info in document_id_info_list:
        for chunk_index in enumerate(
            range(document_id_info.chunk_start_index, document_id_info.chunk_end_index)
        ):
            doc_chunk_ids.append(
                get_uuid_from_chunk_info(
                    document_id=document_id_info.doc_id,
                    chunk_id=chunk_index,
                    tenant_id=tenant_id,
                    large_chunk_id=document_id_info.large_chunk_id,
                )
            )

            if (
                large_chunks_enabled
                and document_id_info.old_version
                and chunk_index % 4 == 0
            ):
                chunk_id = chunk_index / 4
                large_chunk_reference_ids = [
                    chunk_id + i
                    for i in range(4)
                    if chunk_id + i < document_id_info.chunk_end_index
                ]
                doc_chunk_ids.append(
                    get_uuid_from_chunk_info_old(
                        document_id=document_id_info.doc_id,
                        chunk_id=chunk_id,
                        large_chunk_reference_ids=large_chunk_reference_ids,
                    )
                )

    return doc_chunk_ids


def get_uuid_from_chunk_info(
    *,
    document_id: str,
    chunk_id: int,
    tenant_id: str | None,
    large_chunk_id: int | None = None,
) -> uuid.UUID:
    doc_str = document_id

    # Web parsing URL duplicate catching
    if doc_str and doc_str[-1] == "/":
        doc_str = doc_str[:-1]

    chunk_index = (
        "large_" + str(large_chunk_id) if large_chunk_id is not None else str(chunk_id)
    )
    unique_identifier_string = "_".join([doc_str, chunk_index])
    if tenant_id:
        unique_identifier_string += "_" + tenant_id

    return uuid.uuid5(uuid.NAMESPACE_X500, unique_identifier_string)


def get_uuid_from_chunk_info_old(
    *, document_id: str, chunk_id: int, large_chunk_reference_ids: list[str] = []
) -> uuid.UUID:
    doc_str = document_id

    # Web parsing URL duplicate catching
    if doc_str and doc_str[-1] == "/":
        doc_str = doc_str[:-1]
    unique_identifier_string = "_".join([doc_str, str(chunk_id), "0"])
    if large_chunk_reference_ids:
        unique_identifier_string += "_large" + "_".join(
            [
                str(referenced_chunk_id)
                for referenced_chunk_id in large_chunk_reference_ids
            ]
        )
    return uuid.uuid5(uuid.NAMESPACE_X500, unique_identifier_string)


def get_uuid_from_chunk(chunk: DocMetadataAwareIndexChunk) -> uuid.UUID:
    return get_uuid_from_chunk_info(
        chunk.source_document.id, chunk.chunk_id, chunk.large_chunk_id, chunk.tenant_id
    )


def get_uuid_from_chunk_old(
    chunk: DocMetadataAwareIndexChunk, large_chunk_reference_ids: list[str] = []
) -> uuid.UUID:
    return get_uuid_from_chunk_info_old(
        chunk.source_document.id, chunk.chunk_id, large_chunk_reference_ids
    )
