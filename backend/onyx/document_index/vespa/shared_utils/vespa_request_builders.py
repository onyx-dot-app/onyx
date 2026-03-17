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
from onyx.document_index.vespa_constants import PERSONAS
from onyx.document_index.vespa_constants import SOURCE_TYPE
from onyx.document_index.vespa_constants import TENANT_ID
from onyx.document_index.vespa_constants import USER_PROJECT
from onyx.kg.utils.formatting_utils import split_relationship_id
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def build_tenant_id_filter(tenant_id: str) -> str:
    return f'({TENANT_ID} contains "{tenant_id}")'


def build_vespa_filters(
    filters: IndexFilters,
    *,
    include_hidden: bool = False,
    remove_trailing_and: bool = False,  # Set to True when using as a complete Vespa query
) -> str:
    def _build_or_filters(key: str, vals: list[str] | None) -> str:
        """For string-based 'contains' filters, e.g. WSET fields or array<string> fields.
        Returns a bare clause like '(key contains "v1" or key contains "v2")' or ""."""
        if not key or not vals:
            return ""
        eq_elems = [f'{key} contains "{val}"' for val in vals if val]
        if not eq_elems:
            return ""
        return f"({' or '.join(eq_elems)})"

    def _build_weighted_set_filter(key: str, vals: list[str] | None) -> str:
        """Build a Vespa weightedSet filter for large value lists.

        Uses Vespa's native weightedSet() operator instead of OR-chained
        'contains' clauses.  This is critical for fields like
        access_control_list where a single user may have tens of thousands
        of ACL entries — OR clauses at that scale cause Vespa to reject
        the query with HTTP 400."""
        if not key or not vals:
            return ""
        filtered = [val for val in vals if val]
        if not filtered:
            return ""
        items = ", ".join(f'"{val}":1' for val in filtered)
        return f"weightedSet({key}, {{{items}}})"

    def _build_int_or_filters(key: str, vals: list[int] | None) -> str:
        """For an integer field filter.
        Returns a bare clause or ""."""
        if vals is None or not vals:
            return ""
        eq_elems = [f"{key} = {val}" for val in vals]
        return f"({' or '.join(eq_elems)})"

    def _build_kg_filter(
        kg_entities: list[str] | None,
        kg_relationships: list[str] | None,
        kg_terms: list[str] | None,
    ) -> str:
        if not kg_entities and not kg_relationships and not kg_terms:
            return ""

        combined_filter_parts = []

        def _build_kge(entity: str) -> str:
            GENERAL = "::*"
            if entity.endswith(GENERAL):
                return f'({{prefix: true}}"{entity.split(GENERAL, 1)[0]}")'
            else:
                return f'"{entity}"'

        if kg_entities:
            filter_parts = []
            for kg_entity in kg_entities:
                filter_parts.append(f"(kg_entities contains {_build_kge(kg_entity)})")
            combined_filter_parts.append(f"({' or '.join(filter_parts)})")

        # TODO: handle complex nested relationship logic (e.g., A participated, and B or C participated)
        if kg_relationships:
            filter_parts = []
            for kg_relationship in kg_relationships:
                source, rel_type, target = split_relationship_id(kg_relationship)
                filter_parts.append(
                    "(kg_relationships contains sameElement("
                    f"source contains {_build_kge(source)},"
                    f'rel_type contains "{rel_type}",'
                    f"target contains {_build_kge(target)}))"
                )
            combined_filter_parts.append(f"{' and '.join(filter_parts)}")

        # TODO: remove kg terms entirely from prompts and codebase

        return f"({' and '.join(combined_filter_parts)})"

    def _build_kg_source_filters(
        kg_sources: list[str] | None,
    ) -> str:
        if not kg_sources:
            return ""

        source_phrases = [f'{DOCUMENT_ID} contains "{source}"' for source in kg_sources]
        return f"({' or '.join(source_phrases)})"

    def _build_kg_chunk_id_zero_only_filter(
        kg_chunk_id_zero_only: bool,
    ) -> str:
        if not kg_chunk_id_zero_only:
            return ""
        return "(chunk_id = 0)"

    def _build_time_filter(
        cutoff: datetime | None,
        untimed_doc_cutoff: timedelta = timedelta(days=92),
    ) -> str:
        if not cutoff:
            return ""
        include_untimed = datetime.now(timezone.utc) - untimed_doc_cutoff > cutoff
        cutoff_secs = int(cutoff.timestamp())

        if include_untimed:
            return f"!({DOC_UPDATED_AT} < {cutoff_secs})"
        return f"({DOC_UPDATED_AT} >= {cutoff_secs})"

    def _build_user_project_filter(
        project_id: int | None,
    ) -> str:
        if project_id is None:
            return ""
        try:
            pid = int(project_id)
        except Exception:
            return ""
        return f'({USER_PROJECT} contains "{pid}")'

    def _build_persona_filter(
        persona_id: int | None,
    ) -> str:
        if persona_id is None:
            return ""
        try:
            pid = int(persona_id)
        except Exception:
            logger.warning(f"Invalid persona ID: {persona_id}")
            return ""
        return f'({PERSONAS} contains "{pid}")'

    def _append(parts: list[str], clause: str) -> None:
        if clause:
            parts.append(clause)

    # Collect all top-level filter clauses, then join with " and " at the end.
    filter_parts: list[str] = []

    if not include_hidden:
        filter_parts.append(f"!({HIDDEN}=true)")

    # TODO: add error condition if MULTI_TENANT and no tenant_id filter is set
    if filters.tenant_id and MULTI_TENANT:
        filter_parts.append(build_tenant_id_filter(filters.tenant_id))

    # ACL filters — use weightedSet for efficient matching against the
    # access_control_list weightedset<string> field.  OR-chaining thousands
    # of 'contains' clauses causes Vespa to reject the query (HTTP 400)
    # for users with large numbers of external permission groups.
    if filters.access_control_list is not None:
        _append(
            filter_parts,
            _build_weighted_set_filter(
                ACCESS_CONTROL_LIST, filters.access_control_list
            ),
        )

    # Source type filters
    source_strs = (
        [s.value for s in filters.source_type] if filters.source_type else None
    )
    _append(filter_parts, _build_or_filters(SOURCE_TYPE, source_strs))

    # Tag filters
    tag_attributes = None
    if filters.tags:
        tag_attributes = [
            f"{tag.tag_key}{INDEX_SEPARATOR}{tag.tag_value}" for tag in filters.tags
        ]
    _append(filter_parts, _build_or_filters(METADATA_LIST, tag_attributes))

    # Knowledge scope: explicit knowledge attachments (document_sets,
    # user_file_ids) restrict what an assistant can see.  When none are
    # set, the assistant can see everything.
    #
    # project_id / persona_id are additive: they make overflowing user
    # files findable in Vespa but must NOT trigger the restriction on
    # their own (an agent with no explicit knowledge should search
    # everything).
    knowledge_scope_parts: list[str] = []

    _append(
        knowledge_scope_parts, _build_or_filters(DOCUMENT_SETS, filters.document_set)
    )

    user_file_ids_str = (
        [str(uuid) for uuid in filters.user_file_ids] if filters.user_file_ids else None
    )
    _append(knowledge_scope_parts, _build_or_filters(DOCUMENT_ID, user_file_ids_str))

    # Only include project/persona scopes when an explicit knowledge
    # restriction is already in effect — they widen the scope to also
    # cover overflowing user files but never restrict on their own.
    if knowledge_scope_parts:
        _append(knowledge_scope_parts, _build_user_project_filter(filters.project_id))
        _append(knowledge_scope_parts, _build_persona_filter(filters.persona_id))

    if len(knowledge_scope_parts) > 1:
        filter_parts.append("(" + " or ".join(knowledge_scope_parts) + ")")
    elif len(knowledge_scope_parts) == 1:
        filter_parts.append(knowledge_scope_parts[0])

    # Time filter
    _append(filter_parts, _build_time_filter(filters.time_cutoff))

    # # Knowledge Graph Filters
    # _append(filter_parts, _build_kg_filter(
    #     kg_entities=filters.kg_entities,
    #     kg_relationships=filters.kg_relationships,
    #     kg_terms=filters.kg_terms,
    # ))

    # _append(filter_parts, _build_kg_source_filters(filters.kg_sources))

    # _append(filter_parts, _build_kg_chunk_id_zero_only_filter(
    #     filters.kg_chunk_id_zero_only or False
    # ))

    filter_str = " and ".join(filter_parts)

    if filter_str and not remove_trailing_and:
        filter_str += " and "

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
