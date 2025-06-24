from ee.onyx.db.connector_credential_pair import get_all_auto_sync_cc_pairs
from ee.onyx.external_permissions.sync_params import get_all_censoring_enabled_sources
from ee.onyx.external_permissions.sync_params import get_source_perm_sync_config
from onyx.configs.constants import DocumentSource
from onyx.context.search.pipeline import InferenceChunk
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_all_censoring_enabled_sources() -> set[DocumentSource]:
    """
    Returns the set of sources that have censoring enabled.
    This is based on if the access_type is set to sync and the connector
    source has a censoring config.

    NOTE: This means if there is a source has a single cc_pair that is sync,
    all chunks for that source will be censored, even if the connector that
    indexed that chunk is not sync. This was done to avoid getting the cc_pair
    for every single chunk.
    """
    all_censoring_enabled_sources = get_all_censoring_enabled_sources()
    with get_session_with_current_tenant() as db_session:
        enabled_sync_connectors = get_all_auto_sync_cc_pairs(db_session)
        return {
            cc_pair.connector.source
            for cc_pair in enabled_sync_connectors
            if cc_pair.connector.source in all_censoring_enabled_sources
        }


# NOTE: This is only called if ee is enabled.
def _post_query_chunk_censoring(
    chunks: list[InferenceChunk],
    user: User | None,
) -> list[InferenceChunk]:
    """
    This function checks all chunks to see if they need to be sent to a censoring
    function. If they do, it sends them to the censoring function and returns the
    censored chunks. If they don't, it returns the original chunks.
    """
    if user is None:
        # if user is None, permissions are not enforced
        return chunks

    final_chunk_dict: dict[str, InferenceChunk] = {}
    chunks_to_process: dict[DocumentSource, list[InferenceChunk]] = {}

    sources_to_censor = _get_all_censoring_enabled_sources()
    for chunk in chunks:
        # Separate out chunks that require permission post-processing by source
        if chunk.source_type in sources_to_censor:
            chunks_to_process.setdefault(chunk.source_type, []).append(chunk)
        else:
            final_chunk_dict[chunk.unique_id] = chunk

    # For each source, filter out the chunks using the permission
    # check function for that source
    # TODO: Use a threadpool/multiprocessing to process the sources in parallel
    for source, chunks_for_source in chunks_to_process.items():
        sync_config = get_source_perm_sync_config(source)
        if sync_config is None or sync_config.censoring_config is None:
            raise ValueError(f"No sync config found for {source}")

        censor_chunks_for_source = sync_config.censoring_config.chunk_censoring_func
        try:
            censored_chunks = censor_chunks_for_source(chunks_for_source, user.email)
        except Exception as e:
            logger.exception(
                f"Failed to censor chunks for source {source} so throwing out all"
                f" chunks for this source and continuing: {e}"
            )
            continue

        for censored_chunk in censored_chunks:
            final_chunk_dict[censored_chunk.unique_id] = censored_chunk

    # IMPORTANT: make sure to retain the same ordering as the original `chunks` passed in
    final_chunk_list: list[InferenceChunk] = []
    for chunk in chunks:
        # only if the chunk is in the final censored chunks, add it to the final list
        # if it is missing, that means it was intentionally left out
        if chunk.unique_id in final_chunk_dict:
            final_chunk_list.append(final_chunk_dict[chunk.unique_id])

    return final_chunk_list
