from datetime import datetime
from datetime import timedelta
from datetime import timezone

from onyx.configs.constants import INDEX_SEPARATOR
from onyx.context.search.models import IndexFilters
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.vespa_constants import ACCESS_CONTROL_LIST
from onyx.document_index.vespa_constants import CHUNK_ID
from onyx.document_index.vespa_constants import DOC_UPDATED_AT
from onyx.document_index.vespa_constants import DOCUMENT_ID
from onyx.document_index.vespa_constants import DOCUMENT_SETS
from onyx.document_index.vespa_constants import HIDDEN
from onyx.document_index.vespa_constants import METADATA_LIST
from onyx.document_index.vespa_constants import SOURCE_TYPE
from onyx.document_index.vespa_constants import TENANT_ID
from onyx.document_index.vespa_constants import USER_FILE
from onyx.document_index.vespa_constants import USER_FOLDER
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def build_vespa_filters(
    filters: IndexFilters,
    *,
    include_hidden: bool = False,
    remove_trailing_and: bool = False,  # Set to True when using as a complete Vespa query
) -> str:
    def _build_or_filters(key: str, vals: list[str] | None) -> str:
        """For string-based 'contains' filters, e.g. WSET fields or array<string> fields."""
        if not key or not vals:
            return ""
        eq_elems = [f'{key} contains "{val}"' for val in vals if val]
        if not eq_elems:
            return ""
        or_clause = " or ".join(eq_elems)
        return f"({or_clause}) and "

    def _build_int_or_filters(key: str, vals: list[int] | None) -> str:
        """
        For an integer field filter.
        If vals is not None, we want *only* docs whose key matches one of vals.
        """
        # If `vals` is None => skip the filter entirely
        if vals is None or not vals:
            return ""

        # Otherwise build the OR filter
        eq_elems = [f"{key} = {val}" for val in vals]
        or_clause = " or ".join(eq_elems)
        result = f"({or_clause}) and "

        return result

    def _build_kg_filter(
        kg_entities: list[str] | None,
        kg_relationships: list[str] | None,
        kg_terms: list[str] | None,
    ) -> str:
        if not kg_entities and not kg_relationships and not kg_terms:
            return ""

        filter_parts = []

        # Process each filter type using the same pattern
        for filter_type, values in [
            ("kg_entities", kg_entities),
            ("kg_relationships", kg_relationships),
            ("kg_terms", kg_terms),
        ]:
            if values:
                filter_parts.append(
                    " and ".join(f'({filter_type} contains "{val}") ' for val in values)
                )

        return f"({' and '.join(filter_parts)}) and "

    def _build_kg_source_filters(
        kg_sources: list[str] | None,
    ) -> str:
        if not kg_sources:
            return ""

        source_phrases = [f'{DOCUMENT_ID} contains "{source}"' for source in kg_sources]

        return f"({' or '.join(source_phrases)}) and "

    def _build_kg_chunk_id_zero_only_filter(
        kg_chunk_id_zero_only: bool,
    ) -> str:
        if not kg_chunk_id_zero_only:
            return ""

        return "(chunk_id = 0 ) and "

    def _build_time_filter(
        cutoff: datetime | None,
        untimed_doc_cutoff: timedelta = timedelta(days=92),
    ) -> str:
        if not cutoff:
            return ""
        include_untimed = datetime.now(timezone.utc) - untimed_doc_cutoff > cutoff
        cutoff_secs = int(cutoff.timestamp())

        if include_untimed:
            return f"!({DOC_UPDATED_AT} < {cutoff_secs}) and "
        return f"({DOC_UPDATED_AT} >= {cutoff_secs}) and "

    # Start building the filter string
    filter_str = f"!({HIDDEN}=true) and " if not include_hidden else ""

    # TODO: add error condition if MULTI_TENANT and no tenant_id filter is set
    # If running in multi-tenant mode
    if filters.tenant_id and MULTI_TENANT:
        filter_str += f'({TENANT_ID} contains "{filters.tenant_id}") and '

    # ACL filters
    if filters.access_control_list is not None:
        filter_str += _build_or_filters(
            ACCESS_CONTROL_LIST, filters.access_control_list
        )

    # Source type filters
    source_strs = (
        [s.value for s in filters.source_type] if filters.source_type else None
    )
    filter_str += _build_or_filters(SOURCE_TYPE, source_strs)

    # Tag filters
    tag_attributes = None
    if filters.tags:
        # build e.g. "tag_key|tag_value"
        tag_attributes = [
            f"{tag.tag_key}{INDEX_SEPARATOR}{tag.tag_value}" for tag in filters.tags
        ]
    filter_str += _build_or_filters(METADATA_LIST, tag_attributes)

    # Document sets
    filter_str += _build_or_filters(DOCUMENT_SETS, filters.document_set)

    # New: user_file_ids as integer filters
    filter_str += _build_int_or_filters(USER_FILE, filters.user_file_ids)

    filter_str += _build_int_or_filters(USER_FOLDER, filters.user_folder_ids)

    # Time filter
    filter_str += _build_time_filter(filters.time_cutoff)

    # Knowledge Graph Filters
    filter_str += _build_kg_filter(
        kg_entities=filters.kg_entities,
        kg_relationships=filters.kg_relationships,
        kg_terms=filters.kg_terms,
    )

    filter_str += _build_kg_source_filters(filters.kg_sources)

    filter_str += _build_kg_chunk_id_zero_only_filter(
        filters.kg_chunk_id_zero_only or False
    )

    # Trim trailing " and "
    if remove_trailing_and and filter_str.endswith(" and "):
        filter_str = filter_str[:-5]

    return filter_str


def build_vespa_id_based_retrieval_yql(
    chunk_request: VespaChunkRequest,
) -> str:
    id_based_retrieval_yql_section = (
        f'({DOCUMENT_ID} contains "{chunk_request.document_id}"'
    )

    if chunk_request.is_capped:
        id_based_retrieval_yql_section += (
            f" and {CHUNK_ID} >= {chunk_request.min_chunk_ind or 0}"
        )
        id_based_retrieval_yql_section += (
            f" and {CHUNK_ID} <= {chunk_request.max_chunk_ind}"
        )

    id_based_retrieval_yql_section += ")"
    return id_based_retrieval_yql_section
