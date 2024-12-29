from ee.onyx.db.external_perm import fetch_external_groups_for_user_email_and_group_ids
from ee.onyx.external_permissions.salesforce.utils import (
    get_any_salesforce_client_for_doc_id,
)
from ee.onyx.external_permissions.salesforce.utils import get_objects_access_for_user_id
from ee.onyx.external_permissions.salesforce.utils import get_salesforce_user_id
from onyx.configs.app_configs import BLURB_SIZE
from onyx.context.search.models import InferenceChunk
from onyx.db.engine import get_session_context_manager


# Types
ChunkKey = tuple[str, int]  # (doc_id, chunk_id)
ContentRange = tuple[int, int | None]  # (start_index, end_index) None means to the end


def _get_objects_access_for_user_email(
    object_ids: set[str], user_email: str
) -> dict[str, bool]:
    with get_session_context_manager() as db_session:
        external_groups = fetch_external_groups_for_user_email_and_group_ids(
            db_session=db_session,
            user_email=user_email,
            # Maybe make a function that adds a salesforce prefix to the group ids
            group_ids=list(object_ids),
        )
        external_group_ids = {group.external_user_group_id for group in external_groups}
        return {group_id: group_id in external_group_ids for group_id in object_ids}


def _get_objects_access_for_user_email_from_salesforce(
    object_ids: set[str], user_email: str, chunks: list[InferenceChunk]
) -> dict[str, bool]:
    first_doc_id = chunks[0].document_id
    with get_session_context_manager() as db_session:
        salesforce_client = get_any_salesforce_client_for_doc_id(
            db_session, first_doc_id
        )

    user_id = get_salesforce_user_id(salesforce_client, user_email)
    return get_objects_access_for_user_id(salesforce_client, user_id, list(object_ids))


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


def _create_empty_filtered_chunk(unfiltered_chunk: InferenceChunk) -> InferenceChunk:
    """
    Create a copy of the unfiltered chunk where potentially sensitive content is removed
    to be added later if the user has access to each of the sub-objects
    """
    empty_filtered_chunk = InferenceChunk(
        **unfiltered_chunk.model_dump(),
    )
    empty_filtered_chunk.content = ""
    empty_filtered_chunk.blurb = ""
    empty_filtered_chunk.source_links = {}
    return empty_filtered_chunk


def _update_filtered_chunk(
    filtered_chunk: InferenceChunk,
    unfiltered_chunk: InferenceChunk,
    content_range: ContentRange,
) -> InferenceChunk:
    """
    Update the filtered chunk with the content and source links from the unfiltered chunk using the content ranges
    """
    start_index, end_index = content_range

    # Update the content of the filtered chunk
    permitted_content = unfiltered_chunk.content[start_index:end_index]
    filtered_chunk.content = permitted_content + filtered_chunk.content

    # Update the source links of the filtered chunk
    if unfiltered_chunk.source_links is not None:
        if filtered_chunk.source_links is None:
            filtered_chunk.source_links = {}
        link_content = unfiltered_chunk.source_links[start_index]
        filtered_chunk.source_links[len(filtered_chunk.content)] = link_content

    # Update the blurb of the filtered chunk
    filtered_chunk.blurb = filtered_chunk.content[:BLURB_SIZE]

    return filtered_chunk


def validate_salesforce_access(
    chunks: list[InferenceChunk],
    user_email: str,
    access_map: dict[str, bool] | None = None,
) -> list[InferenceChunk]:
    # object_id -> list[((doc_id, chunk_id), (start_index, end_index))]
    object_to_content_map: dict[str, list[tuple[ChunkKey, ContentRange]]] = {}

    # (doc_id, chunk_id) -> chunk
    unfiltered_chunks: dict[ChunkKey, InferenceChunk] = {}

    # keep track of all object ids that we have seen to make it easier to get
    # the access for these object ids
    object_ids: set[str] = set()

    for chunk in chunks:
        chunk_key = (chunk.document_id, chunk.chunk_id)
        # create a dictionary to quickly look up the unfiltered chunk
        unfiltered_chunks[chunk_key] = chunk

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

    filtered_chunks: dict[ChunkKey, InferenceChunk] = {}
    for object_id, content_list in object_to_content_map.items():
        # if the user does not have access to the object, or the object is not in the
        # access_map, do not include its content in the filtered chunks
        if not access_map.get(object_id, False):
            continue

        # if we got this far, the user has access to the object so we can create or update
        # the filtered chunk(s) for this object
        for chunk_key, content_range in content_list:
            if chunk_key not in filtered_chunks:
                filtered_chunks[chunk_key] = _create_empty_filtered_chunk(
                    unfiltered_chunks[chunk_key]
                )

            unfiltered_chunk = unfiltered_chunks[chunk_key]
            filtered_chunks[chunk_key] = _update_filtered_chunk(
                filtered_chunk=filtered_chunks[chunk_key],
                unfiltered_chunk=unfiltered_chunk,
                content_range=content_range,
            )

    return list(filtered_chunks.values())
