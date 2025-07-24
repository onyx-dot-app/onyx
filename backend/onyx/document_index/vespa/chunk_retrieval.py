import json
import string
from collections.abc import Callable
from collections.abc import Mapping
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

import httpx
from retry import retry

from onyx.configs.app_configs import LOG_VESPA_TIMING_INFORMATION
from onyx.configs.app_configs import VESPA_LANGUAGE_OVERRIDE
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa.shared_utils.vespa_request_builders import (
    build_vespa_filters,
)
from onyx.document_index.vespa.shared_utils.vespa_request_builders import (
    build_vespa_id_based_retrieval_yql,
)
from onyx.document_index.vespa_constants import ACCESS_CONTROL_LIST
from onyx.document_index.vespa_constants import BLURB
from onyx.document_index.vespa_constants import BOOST
from onyx.document_index.vespa_constants import CHUNK_CONTEXT
from onyx.document_index.vespa_constants import CHUNK_ID
from onyx.document_index.vespa_constants import CONTENT
from onyx.document_index.vespa_constants import CONTENT_SUMMARY
from onyx.document_index.vespa_constants import DOC_SUMMARY
from onyx.document_index.vespa_constants import DOC_UPDATED_AT
from onyx.document_index.vespa_constants import DOCUMENT_ID
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa_constants import HIDDEN
from onyx.document_index.vespa_constants import IMAGE_FILE_NAME
from onyx.document_index.vespa_constants import LARGE_CHUNK_REFERENCE_IDS
from onyx.document_index.vespa_constants import MAX_ID_SEARCH_QUERY_SIZE
from onyx.document_index.vespa_constants import MAX_OR_CONDITIONS
from onyx.document_index.vespa_constants import METADATA
from onyx.document_index.vespa_constants import METADATA_SUFFIX
from onyx.document_index.vespa_constants import PRIMARY_OWNERS
from onyx.document_index.vespa_constants import RECENCY_BIAS
from onyx.document_index.vespa_constants import SEARCH_ENDPOINT
from onyx.document_index.vespa_constants import SECONDARY_OWNERS
from onyx.document_index.vespa_constants import SECTION_CONTINUATION
from onyx.document_index.vespa_constants import SEMANTIC_IDENTIFIER
from onyx.document_index.vespa_constants import SOURCE_LINKS
from onyx.document_index.vespa_constants import SOURCE_TYPE
from onyx.document_index.vespa_constants import TENANT_ID
from onyx.document_index.vespa_constants import TITLE
from onyx.document_index.vespa_constants import YQL_BASE
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def _process_dynamic_summary(
    dynamic_summary: str, max_summary_length: int = 400
) -> list[str]:
    if not dynamic_summary:
        return []

    current_length = 0
    processed_summary: list[str] = []
    for summary_section in dynamic_summary.split("<sep />"):
        # if we're past the desired max length, break at the last word
        if current_length + len(summary_section) >= max_summary_length:
            summary_section = summary_section[: max_summary_length - current_length]
            summary_section = summary_section.lstrip()  # remove any leading whitespace

            # handle the case where the truncated section is either just a
            # single (partial) word or if it's empty
            first_space = summary_section.find(" ")
            if first_space == -1:
                # add ``...`` to previous section
                if processed_summary:
                    processed_summary[-1] += "..."
                break

            # handle the valid truncated section case
            summary_section = summary_section.rsplit(" ", 1)[0]
            if summary_section[-1] in string.punctuation:
                summary_section = summary_section[:-1]
            summary_section += "..."
            processed_summary.append(summary_section)
            break

        processed_summary.append(summary_section)
        current_length += len(summary_section)

    return processed_summary


def _vespa_hit_to_inference_chunk(
    hit: dict[str, Any], null_score: bool = False
) -> InferenceChunkUncleaned:
    fields = cast(dict[str, Any], hit["fields"])

    # parse fields that are stored as strings, but are really json / datetime
    metadata = json.loads(fields[METADATA]) if METADATA in fields else {}
    updated_at = (
        datetime.fromtimestamp(fields[DOC_UPDATED_AT], tz=timezone.utc)
        if DOC_UPDATED_AT in fields
        else None
    )

    match_highlights = _process_dynamic_summary(
        # fallback to regular `content` if the `content_summary` field
        # isn't present
        dynamic_summary=hit["fields"].get(CONTENT_SUMMARY, hit["fields"][CONTENT]),
    )
    semantic_identifier = fields.get(SEMANTIC_IDENTIFIER, "")
    if not semantic_identifier:
        logger.error(
            f"Chunk with blurb: {fields.get(BLURB, 'Unknown')[:50]}... has no Semantic Identifier"
        )

    source_links = fields.get(SOURCE_LINKS, {})
    source_links_dict_unprocessed = (
        json.loads(source_links) if isinstance(source_links, str) else source_links
    )
    source_links_dict = {
        int(k): v
        for k, v in cast(dict[str, str], source_links_dict_unprocessed).items()
    }

    return InferenceChunkUncleaned(
        chunk_id=fields[CHUNK_ID],
        blurb=fields.get(BLURB, ""),  # Unused
        content=fields[CONTENT],  # Includes extra title prefix and metadata suffix;
        # also sometimes context for contextual rag
        source_links=source_links_dict or {0: ""},
        section_continuation=fields[SECTION_CONTINUATION],
        document_id=fields[DOCUMENT_ID],
        source_type=fields[SOURCE_TYPE],
        # still called `image_file_name` in Vespa for backwards compatibility
        image_file_id=fields.get(IMAGE_FILE_NAME),
        title=fields.get(TITLE),
        semantic_identifier=fields[SEMANTIC_IDENTIFIER],
        boost=fields.get(BOOST, 1),
        recency_bias=fields.get("matchfeatures", {}).get(RECENCY_BIAS, 1.0),
        score=None if null_score else hit.get("relevance", 0),
        hidden=fields.get(HIDDEN, False),
        primary_owners=fields.get(PRIMARY_OWNERS),
        secondary_owners=fields.get(SECONDARY_OWNERS),
        large_chunk_reference_ids=fields.get(LARGE_CHUNK_REFERENCE_IDS, []),
        metadata=metadata,
        metadata_suffix=fields.get(METADATA_SUFFIX),
        doc_summary=fields.get(DOC_SUMMARY, ""),
        chunk_context=fields.get(CHUNK_CONTEXT, ""),
        match_highlights=match_highlights,
        updated_at=updated_at,
    )


def get_chunks_via_visit_api(
    chunk_request: VespaChunkRequest,
    index_name: str,
    filters: IndexFilters,
    field_names: list[str] | None = None,
    get_large_chunks: bool = False,
) -> list[dict]:
    # Constructing the URL for the Visit API
    # NOTE: visit API uses the same URL as the document API, but with different params
    url = DOCUMENT_ID_ENDPOINT.format(index_name=index_name)

    # build the list of fields to retrieve
    field_set_list = (
        [f"{field_name}" for field_name in field_names] if field_names else []
    )
    acl_fieldset_entry = f"{ACCESS_CONTROL_LIST}"
    if (
        field_set_list
        and filters.access_control_list
        and acl_fieldset_entry not in field_set_list
    ):
        field_set_list.append(acl_fieldset_entry)

    if MULTI_TENANT:
        tenant_id_fieldset_entry = f"{TENANT_ID}"
        if tenant_id_fieldset_entry not in field_set_list:
            field_set_list.append(tenant_id_fieldset_entry)

    if field_set_list:
        field_set = f"{index_name}:" + ",".join(field_set_list)
    else:
        field_set = None

    # build filters
    selection = f"{index_name}.document_id=='{chunk_request.document_id}'"

    if chunk_request.is_capped:
        selection += f" and {index_name}.chunk_id>={chunk_request.min_chunk_ind or 0}"
        selection += f" and {index_name}.chunk_id<={chunk_request.max_chunk_ind}"
    if not get_large_chunks:
        selection += f" and {index_name}.large_chunk_reference_ids == null"

    # enforcing tenant_id through a == condition
    if MULTI_TENANT:
        if filters.tenant_id:
            selection += f" and {index_name}.tenant_id=='{filters.tenant_id}'"
        else:
            raise ValueError("Tenant ID is required for multi-tenant")

    # Setting up the selection criteria in the query parameters
    params = {
        # NOTE: Document Selector Language doesn't allow `contains`, so we can't check
        # for the ACL in the selection. Instead, we have to check as a postfilter
        "selection": selection,
        "continuation": None,
        "wantedDocumentCount": 1_000,
        "fieldSet": field_set,
    }

    document_chunks: list[dict] = []
    while True:
        try:
            filtered_params = {k: v for k, v in params.items() if v is not None}
            with get_vespa_http_client() as http_client:
                response = http_client.get(url, params=filtered_params)
                response.raise_for_status()
        except httpx.HTTPError as e:
            error_base = "Failed to query Vespa"
            logger.error(
                f"{error_base}:\n"
                f"Request URL: {e.request.url}\n"
                f"Request Headers: {e.request.headers}\n"
                f"Request Payload: {params}\n"
                f"Exception: {str(e)}"
            )
            raise httpx.HTTPError(error_base) from e

        # Check if the response contains any documents
        response_data = response.json()

        if "documents" in response_data:
            for document in response_data["documents"]:
                if filters.access_control_list:
                    document_acl = document["fields"].get(ACCESS_CONTROL_LIST)
                    if not document_acl or not any(
                        user_acl_entry in document_acl
                        for user_acl_entry in filters.access_control_list
                    ):
                        continue

                if MULTI_TENANT:
                    if not filters.tenant_id:
                        raise ValueError("Tenant ID is required for multi-tenant")
                    document_tenant_id = document["fields"].get(TENANT_ID)
                    if document_tenant_id != filters.tenant_id:
                        logger.error(
                            f"Skipping document {document['document_id']} because "
                            f"it does not belong to tenant {filters.tenant_id}. "
                            "This should never happen."
                        )
                        continue

                document_chunks.append(document)

        # Check for continuation token to handle pagination
        if "continuation" in response_data and response_data["continuation"]:
            params["continuation"] = response_data["continuation"]
        else:
            break  # Exit loop if no continuation token

    return document_chunks


# TODO(rkuo): candidate for removal if not being used
# @retry(tries=10, delay=1, backoff=2)
# def get_all_vespa_ids_for_document_id(
#     document_id: str,
#     index_name: str,
#     filters: IndexFilters | None = None,
#     get_large_chunks: bool = False,
# ) -> list[str]:
#     document_chunks = get_chunks_via_visit_api(
#         chunk_request=VespaChunkRequest(document_id=document_id),
#         index_name=index_name,
#         filters=filters or IndexFilters(access_control_list=None),
#         field_names=[DOCUMENT_ID],
#         get_large_chunks=get_large_chunks,
#     )
#     return [chunk["id"].split("::", 1)[-1] for chunk in document_chunks]


def parallel_visit_api_retrieval(
    index_name: str,
    chunk_requests: list[VespaChunkRequest],
    filters: IndexFilters,
    get_large_chunks: bool = False,
) -> list[InferenceChunkUncleaned]:
    functions_with_args: list[tuple[Callable, tuple]] = [
        (
            get_chunks_via_visit_api,
            (chunk_request, index_name, filters, get_large_chunks),
        )
        for chunk_request in chunk_requests
    ]

    parallel_results = run_functions_tuples_in_parallel(
        functions_with_args, allow_failures=True
    )

    # Any failures to retrieve would give a None, drop the Nones and empty lists
    vespa_chunk_sets = [res for res in parallel_results if res]

    flattened_vespa_chunks = []
    for chunk_set in vespa_chunk_sets:
        flattened_vespa_chunks.extend(chunk_set)

    inference_chunks = [
        _vespa_hit_to_inference_chunk(chunk, null_score=True)
        for chunk in flattened_vespa_chunks
    ]

    return inference_chunks


@retry(tries=3, delay=1, backoff=2)
def query_vespa(
    query_params: Mapping[str, str | int | float],
) -> list[InferenceChunkUncleaned]:
    if "query" in query_params and not cast(str, query_params["query"]).strip():
        raise ValueError("No/empty query received")

    params = dict(
        **query_params,
        **(
            {
                "presentation.timing": True,
            }
            if LOG_VESPA_TIMING_INFORMATION
            else {}
        ),
    )

    if VESPA_LANGUAGE_OVERRIDE:
        params["language"] = VESPA_LANGUAGE_OVERRIDE

    try:
        with get_vespa_http_client() as http_client:
            response = http_client.post(SEARCH_ENDPOINT, json=params)
            response.raise_for_status()
    except httpx.HTTPError as e:
        error_base = "Failed to query Vespa"
        logger.error(
            f"{error_base}:\n"
            f"Request URL: {e.request.url}\n"
            f"Request Headers: {e.request.headers}\n"
            f"Request Payload: {params}\n"
            f"Exception: {str(e)}"
            + (
                f"\nResponse: {e.response.text}"
                if isinstance(e, httpx.HTTPStatusError)
                else ""
            )
        )
        raise httpx.HTTPError(error_base) from e

    response_json: dict[str, Any] = response.json()

    if LOG_VESPA_TIMING_INFORMATION:
        logger.debug("Vespa timing info: %s", response_json.get("timing"))
    hits = response_json["root"].get("children", [])

    if not hits:
        logger.warning(
            f"No hits found for YQL Query: {query_params.get('yql', 'No YQL Query')}"
        )
        logger.debug(f"Vespa Response: {response.text}")

    for hit in hits:
        if hit["fields"].get(CONTENT) is None:
            identifier = hit["fields"].get("documentid") or hit["id"]
            logger.error(
                f"Vespa Index with Vespa ID {identifier} has no contents. "
                f"This is invalid because the vector is not meaningful and keywordsearch cannot "
                f"fetch this document"
            )

    filtered_hits = [hit for hit in hits if hit["fields"].get(CONTENT) is not None]

    inference_chunks = [_vespa_hit_to_inference_chunk(hit) for hit in filtered_hits]

    try:
        num_retrieved_inference_chunks = len(inference_chunks)
        num_retrieved_document_ids = len(
            set([chunk.document_id for chunk in inference_chunks])
        )
        logger.info(
            f"Retrieved {num_retrieved_inference_chunks} inference chunks for {num_retrieved_document_ids} documents"
        )
    except Exception as e:
        # Debug logging only, should not fail the retrieval
        logger.error(f"Error logging retrieval statistics: {e}")

    # Good Debugging Spot
    return inference_chunks


def _get_chunks_via_batch_search(
    index_name: str,
    chunk_requests: list[VespaChunkRequest],
    filters: IndexFilters,
    get_large_chunks: bool = False,
) -> list[InferenceChunkUncleaned]:
    if not chunk_requests:
        return []

    filters_str = build_vespa_filters(filters=filters, include_hidden=True)

    yql = (
        YQL_BASE.format(index_name=index_name)
        + filters_str
        + build_vespa_id_based_retrieval_yql(chunk_requests[0])
    )
    chunk_requests.pop(0)

    for request in chunk_requests:
        yql += " or " + build_vespa_id_based_retrieval_yql(request)
    params: dict[str, str | int | float] = {
        "yql": yql,
        "hits": MAX_ID_SEARCH_QUERY_SIZE,
    }

    inference_chunks = query_vespa(params)
    if not get_large_chunks:
        inference_chunks = [
            chunk for chunk in inference_chunks if not chunk.large_chunk_reference_ids
        ]
    inference_chunks.sort(key=lambda chunk: chunk.chunk_id)
    return inference_chunks


def batch_search_api_retrieval(
    index_name: str,
    chunk_requests: list[VespaChunkRequest],
    filters: IndexFilters,
    get_large_chunks: bool = False,
) -> list[InferenceChunkUncleaned]:
    retrieved_chunks: list[InferenceChunkUncleaned] = []
    capped_requests: list[VespaChunkRequest] = []
    uncapped_requests: list[VespaChunkRequest] = []
    chunk_count = 0
    for req_ind, request in enumerate(chunk_requests, start=1):
        # All requests without a chunk range are uncapped
        # Uncapped requests are retrieved using the Visit API
        range = request.range
        if range is None:
            uncapped_requests.append(request)
            continue

        if (
            chunk_count + range > MAX_ID_SEARCH_QUERY_SIZE
            or req_ind % MAX_OR_CONDITIONS == 0
        ):
            retrieved_chunks.extend(
                _get_chunks_via_batch_search(
                    index_name=index_name,
                    chunk_requests=capped_requests,
                    filters=filters,
                    get_large_chunks=get_large_chunks,
                )
            )
            capped_requests = []
            chunk_count = 0
        capped_requests.append(request)
        chunk_count += range

    if capped_requests:
        retrieved_chunks.extend(
            _get_chunks_via_batch_search(
                index_name=index_name,
                chunk_requests=capped_requests,
                filters=filters,
                get_large_chunks=get_large_chunks,
            )
        )

    if uncapped_requests:
        logger.debug(f"Retrieving {len(uncapped_requests)} uncapped requests")
        retrieved_chunks.extend(
            parallel_visit_api_retrieval(
                index_name, uncapped_requests, filters, get_large_chunks
            )
        )

    return retrieved_chunks
