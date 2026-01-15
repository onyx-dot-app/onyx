from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.context.search.models import BaseFilters
from onyx.context.search.models import ChunkIndexRequest
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.retrieval.search_runner import search_chunks
from onyx.context.search.utils import inference_section_from_chunks
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex
from onyx.llm.interfaces import LLM
from onyx.secondary_llm_flows.source_filter import extract_source_filter
from onyx.secondary_llm_flows.time_filter import extract_time_filter
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import FunctionCall
from onyx.utils.threadpool_concurrency import run_functions_in_parallel
from onyx.utils.timing import log_function_time
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


@log_function_time(print_only=True)
def _build_index_filters(
    user_provided_filters: BaseFilters | None,
    user: User | None,  # Used for ACLs
    project_id: int | None,
    user_file_ids: list[UUID] | None,
    persona_document_sets: list[str] | None,
    persona_time_cutoff: datetime | None,
    db_session: Session,
    auto_detect_filters: bool = False,
    query: str | None = None,
    llm: LLM | None = None,
    bypass_acl: bool = False,
) -> IndexFilters:
    if auto_detect_filters and (llm is None or query is None):
        raise RuntimeError("LLM and query are required for auto detect filters")

    base_filters = user_provided_filters or BaseFilters()

    if (
        user_provided_filters
        and user_provided_filters.document_set is None
        and persona_document_sets is not None
    ):
        base_filters.document_set = persona_document_sets

    time_filter = base_filters.time_cutoff or persona_time_cutoff
    source_filter = base_filters.source_type

    detected_time_filter = None
    detected_source_filter = None
    if auto_detect_filters:
        time_filter_fnc = FunctionCall(extract_time_filter, (query, llm), {})
        if not source_filter:
            source_filter_fnc = FunctionCall(
                extract_source_filter, (query, llm, db_session), {}
            )
        else:
            source_filter_fnc = None

        functions_to_run = [fn for fn in [time_filter_fnc, source_filter_fnc] if fn]
        parallel_results = run_functions_in_parallel(functions_to_run)
        # Detected favor recent is not used for now
        detected_time_filter, _detected_favor_recent = parallel_results[
            time_filter_fnc.result_id
        ]
        if source_filter_fnc:
            detected_source_filter = parallel_results[source_filter_fnc.result_id]

    # If the detected time filter is more recent, use that one
    if time_filter and detected_time_filter and detected_time_filter > time_filter:
        time_filter = detected_time_filter

    # If the user has explicitly set a source filter, use that one
    if not source_filter and detected_source_filter:
        source_filter = detected_source_filter

    # CRITICAL FIX: If user_file_ids are present, we must ensure "user_file"
    # source type is included in the filter, otherwise user files will be excluded!
    if user_file_ids and source_filter:
        from onyx.configs.constants import DocumentSource

        # Add user_file to the source filter if not already present
        if DocumentSource.USER_FILE not in source_filter:
            source_filter = list(source_filter) + [DocumentSource.USER_FILE]
            logger.debug("Added USER_FILE to source_filter for user knowledge search")

    user_acl_filters = (
        None if bypass_acl else build_access_filters_for_user(user, db_session)
    )

    final_filters = IndexFilters(
        user_file_ids=user_file_ids,
        project_id=project_id,
        source_type=source_filter,
        document_set=persona_document_sets,
        time_cutoff=time_filter,
        tags=base_filters.tags,
        access_control_list=user_acl_filters,
        tenant_id=get_current_tenant_id() if MULTI_TENANT else None,
    )

    return final_filters


def merge_individual_chunks(
    chunks: list[InferenceChunk],
) -> list[InferenceSection]:
    """Merge adjacent chunks from the same document into sections.

    Chunks are considered adjacent if their chunk_ids differ by 1 and they
    are from the same document. The section maintains the position of the
    first chunk in the original list.
    """
    if not chunks:
        return []

    # Create a mapping from (document_id, chunk_id) to original index
    # This helps us find the chunk that appears first in the original list
    chunk_to_original_index: dict[tuple[str, int], int] = {}
    for idx, chunk in enumerate(chunks):
        chunk_to_original_index[(chunk.document_id, chunk.chunk_id)] = idx

    # Group chunks by document_id
    doc_chunks: dict[str, list[InferenceChunk]] = defaultdict(list)
    for chunk in chunks:
        doc_chunks[chunk.document_id].append(chunk)

    # For each document, sort chunks by chunk_id to identify adjacent chunks
    for doc_id in doc_chunks:
        doc_chunks[doc_id].sort(key=lambda c: c.chunk_id)

    # Create a mapping from (document_id, chunk_id) to the section it belongs to
    # This helps us maintain the original order
    chunk_to_section: dict[tuple[str, int], InferenceSection] = {}

    # Process each document's chunks
    for doc_id, doc_chunk_list in doc_chunks.items():
        if not doc_chunk_list:
            continue

        # Group adjacent chunks into sections
        current_section_chunks = [doc_chunk_list[0]]

        for i in range(1, len(doc_chunk_list)):
            prev_chunk = doc_chunk_list[i - 1]
            curr_chunk = doc_chunk_list[i]

            # Check if chunks are adjacent (chunk_id difference is 1)
            if curr_chunk.chunk_id == prev_chunk.chunk_id + 1:
                # Add to current section
                current_section_chunks.append(curr_chunk)
            else:
                # Create section from previous chunks
                # Find the chunk that appears first in the original list
                center_chunk = min(
                    current_section_chunks,
                    key=lambda c: chunk_to_original_index.get(
                        (c.document_id, c.chunk_id), float("inf")
                    ),
                )
                section = inference_section_from_chunks(
                    center_chunk=center_chunk,
                    chunks=current_section_chunks.copy(),
                )
                if section:
                    for chunk in current_section_chunks:
                        chunk_to_section[(chunk.document_id, chunk.chunk_id)] = section

                # Start new section
                current_section_chunks = [curr_chunk]

        # Create section for the last group
        if current_section_chunks:
            # Find the chunk that appears first in the original list
            center_chunk = min(
                current_section_chunks,
                key=lambda c: chunk_to_original_index.get(
                    (c.document_id, c.chunk_id), float("inf")
                ),
            )
            section = inference_section_from_chunks(
                center_chunk=center_chunk,
                chunks=current_section_chunks.copy(),
            )
            if section:
                for chunk in current_section_chunks:
                    chunk_to_section[(chunk.document_id, chunk.chunk_id)] = section

    # Build result list maintaining original order
    # Use (document_id, chunk_id) of center_chunk as unique identifier for sections
    seen_section_ids: set[tuple[str, int]] = set()
    result: list[InferenceSection] = []

    for chunk in chunks:
        section = chunk_to_section.get((chunk.document_id, chunk.chunk_id))
        if section:
            section_id = (
                section.center_chunk.document_id,
                section.center_chunk.chunk_id,
            )
            if section_id not in seen_section_ids:
                seen_section_ids.add(section_id)
                result.append(section)
        else:
            # Chunk wasn't part of any merged section, create a single-chunk section
            single_section = inference_section_from_chunks(
                center_chunk=chunk,
                chunks=[chunk],
            )
            if single_section:
                single_section_id = (
                    single_section.center_chunk.document_id,
                    single_section.center_chunk.chunk_id,
                )
                if single_section_id not in seen_section_ids:
                    seen_section_ids.add(single_section_id)
                    result.append(single_section)

    return result


@log_function_time(print_only=True, debug_only=True)
def search_pipeline(
    # Query and settings
    chunk_search_request: ChunkSearchRequest,
    # Document index to search over
    # Note that federated sources will also be used (not related to this arg)
    document_index: DocumentIndex,
    # Used for ACLs and federated search
    user: User | None,
    # Used for default filters and settings
    persona: Persona | None,
    db_session: Session,
    auto_detect_filters: bool = False,
    llm: LLM | None = None,
    # If a project ID is provided, it will be exclusively scoped to that project
    project_id: int | None = None,
) -> list[InferenceChunk]:
    user_uploaded_persona_files: list[UUID] | None = (
        [user_file.id for user_file in persona.user_files] if persona else None
    )

    persona_document_sets: list[str] | None = (
        [persona_document_set.name for persona_document_set in persona.document_sets]
        if persona
        else None
    )
    persona_time_cutoff: datetime | None = (
        persona.search_start_date if persona else None
    )

    filters = _build_index_filters(
        user_provided_filters=chunk_search_request.user_selected_filters,
        user=user,
        project_id=project_id,
        user_file_ids=user_uploaded_persona_files,
        persona_document_sets=persona_document_sets,
        persona_time_cutoff=persona_time_cutoff,
        db_session=db_session,
        auto_detect_filters=auto_detect_filters,
        query=chunk_search_request.query,
        llm=llm,
        bypass_acl=chunk_search_request.bypass_acl,
    )

    query_request = ChunkIndexRequest(
        query=chunk_search_request.query,
        hybrid_alpha=chunk_search_request.hybrid_alpha,
        recency_bias_multiplier=chunk_search_request.recency_bias_multiplier,
        query_keywords=chunk_search_request.query_keywords,
        filters=filters,
    )

    retrieved_chunks = search_chunks(
        query_request=query_request,
        user_id=user.id if user else None,
        document_index=document_index,
        db_session=db_session,
    )

    # For some specific connectors like Salesforce, a user that has access to an object doesn't mean
    # that they have access to all of the fields of the object.
    censored_chunks: list[InferenceChunk] = fetch_ee_implementation_or_noop(
        "onyx.external_permissions.post_query_censoring",
        "_post_query_chunk_censoring",
        retrieved_chunks,
    )(
        chunks=retrieved_chunks,
        user=user,
    )

    return censored_chunks
