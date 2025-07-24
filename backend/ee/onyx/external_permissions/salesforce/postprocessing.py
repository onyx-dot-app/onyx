import time

from ee.onyx.db.external_perm import fetch_external_groups_for_user_email_and_group_ids
from ee.onyx.external_permissions.salesforce.utils import (
    get_any_salesforce_client_for_doc_id,
)
from ee.onyx.external_permissions.salesforce.utils import get_objects_access_for_user_id
from ee.onyx.external_permissions.salesforce.utils import (
    get_salesforce_user_id_from_email,
)
from onyx.configs.app_configs import BLURB_SIZE
from onyx.context.search.models import InferenceChunk
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Types
ChunkKey = tuple[str, int]  # (doc_id, chunk_id)
ContentRange = tuple[int, int | None]  # (start_index, end_index) None means to the end


# NOTE: Used for testing timing
def _get_dummy_object_access_map(
    object_ids: set[str], user_email: str, chunks: list[InferenceChunk]
) -> dict[str, bool]:
    time.sleep(0.15)
    # return {object_id: True for object_id in object_ids}
    import random

    return {object_id: random.choice([True, False]) for object_id in object_ids}


def _get_objects_access_for_user_email_from_salesforce(
    object_ids: set[str],
    user_email: str,
    chunks: list[InferenceChunk],
) -> dict[str, bool] | None:
    """
    This function wraps the salesforce call as we may want to change how this
    is done in the future. (E.g. replace it with the above function)
    """
    # This is cached in the function so the first query takes an extra 0.1-0.3 seconds
    # but subsequent queries for this source are essentially instant
    first_doc_id = chunks[0].document_id
    with get_session_with_current_tenant() as db_session:
        salesforce_client = get_any_salesforce_client_for_doc_id(
            db_session, first_doc_id
        )

    # This is cached in the function so the first query takes an extra 0.1-0.3 seconds
    # but subsequent queries by the same user are essentially instant
    start_time = time.monotonic()
    user_id = get_salesforce_user_id_from_email(salesforce_client, user_email)
    end_time = time.monotonic()
    logger.info(
        f"Time taken to get Salesforce user ID: {end_time - start_time} seconds"
    )
    if user_id is None:
        logger.warning(f"User '{user_email}' not found in Salesforce")
        return None

    # This is the only query that is not cached in the function
    # so it takes 0.1-0.2 seconds total
    object_id_to_access = get_objects_access_for_user_id(
        salesforce_client, user_id, list(object_ids)
    )
    logger.debug(f"Object ID to access: {object_id_to_access}")
    return object_id_to_access


def _extract_salesforce_object_id_from_url(url: str) -> str:
    return url.split("/")[-1]


def _get_object_ranges_for_chunk(
    chunk: InferenceChunk,
) -> dict[str, list[ContentRange]]:
    """
    Given a chunk, return a dictionary of salesforce object ids and the content ranges
    for that object id in the current chunk
    """
    if chunk.source_links is None:
        return {}

    object_ranges: dict[str, list[ContentRange]] = {}
    end_index = None
    descending_source_links = sorted(
        chunk.source_links.items(), key=lambda x: x[0], reverse=True
    )
    for start_index, url in descending_source_links:
        object_id = _extract_salesforce_object_id_from_url(url)
        if object_id not in object_ranges:
            object_ranges[object_id] = []
        object_ranges[object_id].append((start_index, end_index))
        end_index = start_index
    return object_ranges


def _create_empty_censored_chunk(uncensored_chunk: InferenceChunk) -> InferenceChunk:
    """
    Create a copy of the unfiltered chunk where potentially sensitive content is removed
    to be added later if the user has access to each of the sub-objects
    """
    empty_censored_chunk = InferenceChunk(
        **uncensored_chunk.model_dump(),
    )
    empty_censored_chunk.content = ""
    empty_censored_chunk.blurb = ""
    empty_censored_chunk.source_links = {}
    return empty_censored_chunk


def _update_censored_chunk(
    censored_chunk: InferenceChunk,
    uncensored_chunk: InferenceChunk,
    content_range: ContentRange,
) -> InferenceChunk:
    """
    Update the filtered chunk with the content and source links from the unfiltered chunk using the content ranges
    """
    start_index, end_index = content_range

    # Update the content of the filtered chunk
    permitted_content = uncensored_chunk.content[start_index:end_index]
    permitted_section_start_index = len(censored_chunk.content)
    censored_chunk.content = permitted_content + censored_chunk.content

    # Update the source links of the filtered chunk
    if uncensored_chunk.source_links is not None:
        if censored_chunk.source_links is None:
            censored_chunk.source_links = {}
        link_content = uncensored_chunk.source_links[start_index]
        censored_chunk.source_links[permitted_section_start_index] = link_content

    # Update the blurb of the filtered chunk
    censored_chunk.blurb = censored_chunk.content[:BLURB_SIZE]

    return censored_chunk


# TODO: Generalize this to other sources
def censor_salesforce_chunks(
    chunks: list[InferenceChunk],
    user_email: str,
    # This is so we can provide a mock access map for testing
    access_map: dict[str, bool] | None = None,
) -> list[InferenceChunk]:
    # object_id -> list[((doc_id, chunk_id), (start_index, end_index))]
    object_to_content_map: dict[str, list[tuple[ChunkKey, ContentRange]]] = {}

    # (doc_id, chunk_id) -> chunk
    uncensored_chunks: dict[ChunkKey, InferenceChunk] = {}

    # keep track of all object ids that we have seen to make it easier to get
    # the access for these object ids
    object_ids: set[str] = set()

    for chunk in chunks:
        chunk_key = (chunk.document_id, chunk.chunk_id)
        # create a dictionary to quickly look up the unfiltered chunk
        uncensored_chunks[chunk_key] = chunk

        # for each chunk, get a dictionary of object ids and the content ranges
        # for that object id in the current chunk
        object_ranges_for_chunk = _get_object_ranges_for_chunk(chunk)
        for object_id, ranges in object_ranges_for_chunk.items():
            object_ids.add(object_id)
            for start_index, end_index in ranges:
                object_to_content_map.setdefault(object_id, []).append(
                    (chunk_key, (start_index, end_index))
                )

    # This is so we can provide a mock access map for testing
    if access_map is None:
        access_map = _get_objects_access_for_user_email_from_salesforce(
            object_ids=object_ids,
            user_email=user_email,
            chunks=chunks,
        )
        if access_map is None:
            # If the user is not found in Salesforce, access_map will be None
            # so we should just return an empty list because no chunks will be
            # censored
            return []

    censored_chunks: dict[ChunkKey, InferenceChunk] = {}
    for object_id, content_list in object_to_content_map.items():
        # if the user does not have access to the object, or the object is not in the
        # access_map, do not include its content in the filtered chunks
        if not access_map.get(object_id, False):
            continue

        # if we got this far, the user has access to the object so we can create or update
        # the filtered chunk(s) for this object
        # NOTE: we only create a censored chunk if the user has access to some
        # part of the chunk
        for chunk_key, content_range in content_list:
            if chunk_key not in censored_chunks:
                censored_chunks[chunk_key] = _create_empty_censored_chunk(
                    uncensored_chunks[chunk_key]
                )

            uncensored_chunk = uncensored_chunks[chunk_key]
            censored_chunk = _update_censored_chunk(
                censored_chunk=censored_chunks[chunk_key],
                uncensored_chunk=uncensored_chunk,
                content_range=content_range,
            )
            censored_chunks[chunk_key] = censored_chunk

    return list(censored_chunks.values())


# NOTE: This is not used anywhere.
def _get_objects_access_for_user_email(
    object_ids: set[str], user_email: str
) -> dict[str, bool]:
    with get_session_with_current_tenant() as db_session:
        external_groups = fetch_external_groups_for_user_email_and_group_ids(
            db_session=db_session,
            user_email=user_email,
            # Maybe make a function that adds a salesforce prefix to the group ids
            group_ids=list(object_ids),
        )
        external_group_ids = {group.external_user_group_id for group in external_groups}
        return {group_id: group_id in external_group_ids for group_id in object_ids}
