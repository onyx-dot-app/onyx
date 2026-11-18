from onyx.context.search.models import BaseFilters, PersonaSearchInfo
from onyx.context.search.pipeline import apply_search_start_floor
from onyx.db.postgres_tool_models import DocumentScope


def build_document_scope(
    persona_search: PersonaSearchInfo | None,
    user_selected_filters: BaseFilters | None,
    project_id_filter: int | None,
    persona_id_filter: int | None,
) -> DocumentScope:
    """The scope that SearchTool searches with (`_build_index_filters`), in the
    form the Postgres tool applies."""
    includes_user_files = project_id_filter is not None or persona_id_filter is not None
    if project_id_filter is not None and persona_id_filter is None:
        # Project-only search: only the project's files, and the request
        # filters do not apply.
        return DocumentScope(includes_user_files=True)

    filters = user_selected_filters or BaseFilters()
    # The request's document sets replace the persona's.
    document_set_names = (
        filters.document_set
        if filters.document_set is not None
        else (persona_search.document_set_names if persona_search else [])
    )
    return DocumentScope(
        document_set_names=document_set_names,
        attached_document_ids=(
            persona_search.attached_document_ids if persona_search else []
        ),
        hierarchy_node_ids=persona_search.hierarchy_node_ids if persona_search else [],
        includes_user_files=includes_user_files,
        source_types=filters.source_type,
        updated_at_range=apply_search_start_floor(
            filters.updated_at_range,
            persona_search.search_start_date if persona_search else None,
        ),
        created_at_range=filters.created_at_range,
        tags=filters.tags,
    )
