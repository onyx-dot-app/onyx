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
        if vals is None:
            return ""

        valid_vals = [val for val in vals if val]
        if not key or not valid_vals:
            return ""

        eq_elems = [f'{key} contains "{elem}"' for elem in valid_vals]
        or_clause = " or ".join(eq_elems)
        result = f"({or_clause}) and "

        return result

    def _build_time_filter(
        cutoff: datetime | None,
        # Slightly over 3 Months, approximately 1 fiscal quarter
        untimed_doc_cutoff: timedelta = timedelta(days=92),
    ) -> str:
        if not cutoff:
            return ""

        # For Documents that don't have an updated at, filter them out for queries asking for
        # very recent documents (3 months) default. Documents that don't have an updated at
        # time are assigned 3 months for time decay value
        include_untimed = datetime.now(timezone.utc) - untimed_doc_cutoff > cutoff
        cutoff_secs = int(cutoff.timestamp())

        if include_untimed:
            # Documents without updated_at are assigned -1 as their date
            return f"!({DOC_UPDATED_AT} < {cutoff_secs}) and "

        return f"({DOC_UPDATED_AT} >= {cutoff_secs}) and "

    filter_str = f"!({HIDDEN}=true) and " if not include_hidden else ""

    # If running in multi-tenant mode, we may want to filter by tenant_id
    if filters.tenant_id and MULTI_TENANT:
        filter_str += f'({TENANT_ID} contains "{filters.tenant_id}") and '

    # CAREFUL touching this one, currently there is no second ACL double-check post retrieval
    if filters.access_control_list is not None:
        filter_str += _build_or_filters(
            ACCESS_CONTROL_LIST, filters.access_control_list
        )

    source_strs = (
        [s.value for s in filters.source_type] if filters.source_type else None
    )
    filter_str += _build_or_filters(SOURCE_TYPE, source_strs)

    tag_attributes = None
    tags = filters.tags
    if tags:
        tag_attributes = [tag.tag_key + INDEX_SEPARATOR + tag.tag_value for tag in tags]
    filter_str += _build_or_filters(METADATA_LIST, tag_attributes)

    filter_str += _build_or_filters(DOCUMENT_SETS, filters.document_set)

    filter_str += _build_time_filter(filters.time_cutoff)

    if remove_trailing_and and filter_str.endswith(" and "):
        filter_str = filter_str[:-5]  # We remove the trailing " and "

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
