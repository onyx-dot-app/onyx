from ee.onyx.external_permissions.sync_params import (
    CensoringConfig,
    get_all_censoring_enabled_sources,
    get_source_perm_sync_config,
)
from onyx.configs.constants import DocumentSource
from onyx.context.search.pipeline import InferenceChunk
from onyx.db.document import get_document_access_types
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _censoring_config(source: DocumentSource) -> CensoringConfig:
    sync_config = get_source_perm_sync_config(source)
    if sync_config is None or sync_config.censoring_config is None:
        raise ValueError(f"No censoring config found for {source}")
    return sync_config.censoring_config


def _get_censored_document_ids(
    doc_ids_by_source: dict[DocumentSource, set[str]],
) -> set[str]:
    """Documents whose access is decided at query time. One under a public
    cc_pair is open outright. Otherwise one under a perm-synced cc_pair is
    censored, one with no cc_pair left is censored rather than passed through,
    and one under only private cc_pairs is censored when its source's
    censoring config says so."""
    document_ids: set[str] = set().union(*doc_ids_by_source.values())
    if not document_ids:
        return set()
    with get_session_with_current_tenant() as db_session:
        access_types: dict[str, set[AccessType]] = get_document_access_types(
            db_session, list(document_ids)
        )
    censored_doc_ids: set[str] = set()
    for source, doc_ids in doc_ids_by_source.items():
        censors_private: bool = _censoring_config(source).censors_private_connectors
        for doc_id in doc_ids:
            types: set[AccessType] = access_types.get(doc_id, set())
            if AccessType.PUBLIC in types:
                continue
            if (
                not types
                or censors_private
                or any(access_type.is_perm_synced() for access_type in types)
            ):
                censored_doc_ids.add(doc_id)
    return censored_doc_ids


# NOTE: This is only called if ee is enabled.
def _post_query_chunk_censoring(
    chunks: list[InferenceChunk],
    user: User,
) -> list[InferenceChunk]:
    """Runs chunks of censored documents through their source's censoring
    function and passes every other chunk through unchanged."""
    censoring_sources = get_all_censoring_enabled_sources()
    doc_ids_by_source: dict[DocumentSource, set[str]] = {}
    for chunk in chunks:
        if chunk.source_type in censoring_sources:
            doc_ids_by_source.setdefault(chunk.source_type, set()).add(
                chunk.document_id
            )
    censored_doc_ids = _get_censored_document_ids(doc_ids_by_source)

    final_chunk_dict: dict[str, InferenceChunk] = {}
    chunks_to_process: dict[DocumentSource, list[InferenceChunk]] = {}
    for chunk in chunks:
        if chunk.document_id not in censored_doc_ids:
            final_chunk_dict[chunk.unique_id] = chunk
            continue
        # Anonymous users have no identity to check against the source.
        if user.is_anonymous:
            continue
        chunks_to_process.setdefault(chunk.source_type, []).append(chunk)

    # For each source, filter out the chunks using the permission
    # check function for that source
    # TODO: Use a threadpool/multiprocessing to process the sources in parallel
    for source, chunks_for_source in chunks_to_process.items():
        censor_chunks_for_source = _censoring_config(source).chunk_censoring_func
        try:
            censored_chunks = censor_chunks_for_source(chunks_for_source, user.email)
        except Exception:
            logger.exception(
                "Failed to censor chunks for source %s so throwing out all chunks for this source and continuing",
                source,
            )
            continue

        for censored_chunk in censored_chunks:
            final_chunk_dict[censored_chunk.unique_id] = censored_chunk

    # IMPORTANT: make sure to retain the same ordering as the original `chunks` passed in
    # only if the chunk is in the final censored chunks, add it to the final list
    # if it is missing, that means it was intentionally left out
    final_chunk_list: list[InferenceChunk] = [
        final_chunk_dict[chunk.unique_id]
        for chunk in chunks
        if chunk.unique_id in final_chunk_dict
    ]

    return final_chunk_list
